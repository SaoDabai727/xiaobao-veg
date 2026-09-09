"""GitHub Releases 云端升级：查版本、下载、合并安装（跳过 data/）。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from packaging.version import InvalidVersion, Version

from app import APP_NAME, __version__
from app.storage import app_root

EXE_NAME = f"{APP_NAME}.exe"

GITHUB_OWNER = "SaoDabai727"
GITHUB_REPO = "xiaobao-veg"
ASSET_PREFIX = "xiaobao-veg-"
API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
USER_AGENT = "xiaobao-veg-updater"

# 国内直连 GitHub 常超时：按顺序尝试原址 + 公共加速前缀
_MIRROR_PREFIXES = (
    "",  # 官方原址
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://mirror.ghproxy.com/",
)

# 约 120MB 包在慢网下可能要十几分钟
DOWNLOAD_TIMEOUT = 1800.0
DOWNLOAD_CHUNK = 256 * 1024
PROGRESS_MIN_INTERVAL = 0.35


@dataclass
class ReleaseInfo:
    version: str
    tag: str
    notes: str
    asset_name: str
    download_url: str


def normalize_version(tag_or_version: str) -> str:
    s = (tag_or_version or "").strip()
    if s.lower().startswith("v"):
        s = s[1:]
    return s


def is_newer(remote: str, local: str) -> bool:
    try:
        return Version(normalize_version(remote)) > Version(normalize_version(local))
    except InvalidVersion:
        return False


def _urlopen(req: urllib.request.Request, timeout: float, *, use_proxy: bool = True):
    """打开 URL；use_proxy=False 时忽略环境代理（避免本机失效代理拖死下载）。"""
    if use_proxy:
        return urllib.request.urlopen(req, timeout=timeout)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(req, timeout=timeout)


def _request_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with _urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest_release(timeout: float = 15.0) -> ReleaseInfo | None:
    try:
        data = _request_json(API_LATEST, timeout=timeout)
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ):
        # API 偶发被墙：再试一次无代理
        try:
            req = urllib.request.Request(
                API_LATEST,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.github+json",
                },
            )
            with _urlopen(req, timeout=timeout, use_proxy=False) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
        ):
            return None

    tag = str(data.get("tag_name") or "")
    version = normalize_version(tag)
    if not version:
        return None

    notes = str(data.get("body") or "").strip()
    assets = data.get("assets") or []
    asset_name = ""
    download_url = ""
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.startswith(ASSET_PREFIX) and name.lower().endswith(".zip"):
            asset_name = name
            download_url = str(asset.get("browser_download_url") or "")
            break
    if not download_url:
        # 兜底：任意 zip
        for asset in assets:
            name = str(asset.get("name") or "")
            if name.lower().endswith(".zip"):
                asset_name = name
                download_url = str(asset.get("browser_download_url") or "")
                break
    if not download_url:
        return None

    return ReleaseInfo(
        version=version,
        tag=tag,
        notes=notes,
        asset_name=asset_name,
        download_url=download_url,
    )


def check_for_update(timeout: float = 15.0) -> ReleaseInfo | None:
    info = fetch_latest_release(timeout=timeout)
    if info is None:
        return None
    if not is_newer(info.version, __version__):
        return None
    return info


def mirror_download_urls(url: str) -> list[str]:
    """原址 + 镜像前缀；去重保序。"""
    url = (url or "").strip()
    if not url:
        return []
    out: list[str] = []
    for prefix in _MIRROR_PREFIXES:
        cand = f"{prefix}{url}" if prefix else url
        if cand not in out:
            out.append(cand)
    return out


def format_download_progress(
    done: int,
    total: int | None,
    speed_bps: float | None = None,
) -> tuple[str, float]:
    """返回 (状态文案, 0~1 进度)。无总长时进度按已下量缓慢爬升到 0.9。"""
    done_mb = done / (1024 * 1024)
    speed_txt = ""
    if speed_bps and speed_bps > 0:
        if speed_bps >= 1024 * 1024:
            speed_txt = f" · {speed_bps / (1024 * 1024):.1f} MB/s"
        else:
            speed_txt = f" · {speed_bps / 1024:.0f} KB/s"

    if total and total > 0:
        pct = max(0, min(100, int(done * 100 / total)))
        total_mb = total / (1024 * 1024)
        text = f"正在下载更新… {done_mb:.1f}/{total_mb:.1f} MB（{pct}%）{speed_txt}"
        return text, done / total

    fake = min(0.9, done_mb / 150.0)
    text = f"正在下载更新… 已下 {done_mb:.1f} MB{speed_txt}"
    return text, fake


def download_file(
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int | None, float | None], None] | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
    *,
    use_proxy: bool = True,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _urlopen(req, timeout=timeout, use_proxy=use_proxy) as resp:
        total_hdr = resp.headers.get("Content-Length")
        total = int(total_hdr) if total_hdr and total_hdr.isdigit() else None
        done = 0
        last_cb = 0.0
        t0 = time.time()
        last_done = 0
        last_t = t0
        speed: float | None = None
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last_t >= 0.5:
                    dt = now - last_t
                    if dt > 0:
                        speed = (done - last_done) / dt
                    last_done = done
                    last_t = now
                if progress_cb and (
                    now - last_cb >= PROGRESS_MIN_INTERVAL or (total and done >= total)
                ):
                    last_cb = now
                    progress_cb(done, total, speed)
        if progress_cb:
            elapsed = max(time.time() - t0, 1e-3)
            progress_cb(done, total or done, done / elapsed)


def download_release_asset(
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int | None, float | None], None] | None = None,
    status_cb: Callable[[str], None] | None = None,
    timeout: float = DOWNLOAD_TIMEOUT,
) -> str:
    """依次尝试原址/镜像与代理/无代理；成功返回实际 URL。"""
    errors: list[str] = []
    urls = mirror_download_urls(url)
    for idx, cand in enumerate(urls):
        # 官方首试限时较短，卡住就换镜像；镜像给足时间
        attempt_timeout = 180.0 if idx == 0 else timeout
        for use_proxy in (True, False):
            if status_cb:
                if idx == 0 and use_proxy:
                    status_cb("正在下载更新…（官方源）")
                elif idx > 0 and use_proxy:
                    status_cb(f"正在下载更新…（加速线路 {idx}/{len(urls) - 1}）")
            label = "代理" if use_proxy else "直连"
            try:
                if dest.exists():
                    dest.unlink()
                download_file(
                    cand,
                    dest,
                    progress_cb=progress_cb,
                    timeout=attempt_timeout,
                    use_proxy=use_proxy,
                )
                if dest.stat().st_size < 1024:
                    raise OSError("下载文件过小，可能不是完整安装包")
                return cand
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label} {cand}: {exc}")
                try:
                    if dest.exists():
                        dest.unlink()
                except OSError:
                    pass
    detail = "\n".join(errors[-6:])
    raise OSError(
        "下载失败（已尝试官方与多个镜像）。\n"
        "可到 GitHub Releases 手动下载安装包覆盖安装。\n\n"
        f"{detail}"
    )


def extract_release_zip(zip_path: Path, dest_dir: Path) -> Path:
    """解压 zip，返回内含 exe 的应用根目录。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    # 优先：蔬菜汇总/蔬菜汇总.exe
    preferred = dest_dir / APP_NAME
    if (preferred / EXE_NAME).is_file():
        return preferred

    # 递归查找
    for p in dest_dir.rglob(EXE_NAME):
        return p.parent

    raise FileNotFoundError(f"zip 内未找到 {EXE_NAME}")


def merge_install(src_root: Path, dest_root: Path) -> None:
    """将 src 合并到 dest；永不覆盖顶层 data/。"""
    dest_root.mkdir(parents=True, exist_ok=True)
    for item in src_root.iterdir():
        if item.name.lower() == "data":
            continue
        target = dest_root / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _wait_pid(pid: int, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            # Windows: os.kill(pid, 0) 在进程不存在时抛出
            os.kill(pid, 0)
        except OSError:
            return
        except SystemError:
            return
        time.sleep(0.4)
    # 超时也继续尝试合并


def _start_app(install_root: Path) -> None:
    exe = install_root / EXE_NAME
    if exe.is_file():
        subprocess.Popen(
            [str(exe)],
            cwd=str(install_root),
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        return
    # 开发模式
    run_py = install_root / "run.py"
    if run_py.is_file():
        subprocess.Popen(
            [sys.executable, str(run_py)],
            cwd=str(install_root),
            close_fds=True,
        )


def apply_update_main(argv: list[str]) -> int:
    """argv: prog --apply-update <src_root> <dest_root> <pid>"""
    if len(argv) < 5:
        print("usage: --apply-update <src> <dest> <pid>", file=sys.stderr)
        return 2
    src = Path(argv[2])
    dest = Path(argv[3])
    try:
        pid = int(argv[4])
    except ValueError:
        return 2

    _wait_pid(pid)
    time.sleep(0.6)
    try:
        merge_install(src, dest)
    except Exception as exc:  # noqa: BLE001
        log = Path(tempfile.gettempdir()) / "xiaobao-update-error.txt"
        log.write_text(f"{exc}\n", encoding="utf-8")
        return 1

    _start_app(dest)

    # 清理解压父目录（src 的上一级常为临时解压根）
    try:
        parent = src.parent
        if parent.name.startswith("xiaobao-update-"):
            shutil.rmtree(parent, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return 0


def spawn_apply_and_exit(src_root: Path, dest_root: Path) -> None:
    pid = os.getpid()
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--apply-update", str(src_root), str(dest_root), str(pid)]
    else:
        # 开发：用当前解释器跑 run.py
        run_py = Path(__file__).resolve().parent.parent / "run.py"
        cmd = [
            sys.executable,
            str(run_py),
            "--apply-update",
            str(src_root),
            str(dest_root),
            str(pid),
        ]

    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    subprocess.Popen(cmd, close_fds=True, creationflags=flags)
    os._exit(0)


def prepare_update_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="xiaobao-update-"))


def install_root() -> Path:
    return app_root()
