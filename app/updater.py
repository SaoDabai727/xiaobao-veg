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

from app import __version__
from app.storage import app_root

GITHUB_OWNER = "SaoDabai727"
GITHUB_REPO = "xiaobao-veg"
ASSET_PREFIX = "小宝蔬菜汇总-"
API_LATEST = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
USER_AGENT = "xiaobao-veg-updater"


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


def _request_json(url: str, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_latest_release(timeout: float = 8.0) -> ReleaseInfo | None:
    try:
        data = _request_json(API_LATEST, timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
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


def check_for_update(timeout: float = 8.0) -> ReleaseInfo | None:
    info = fetch_latest_release(timeout=timeout)
    if info is None:
        return None
    if not is_newer(info.version, __version__):
        return None
    return info


def download_file(
    url: str,
    dest: Path,
    progress_cb: Callable[[int, int | None], None] | None = None,
    timeout: float = 120.0,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total_hdr = resp.headers.get("Content-Length")
        total = int(total_hdr) if total_hdr and total_hdr.isdigit() else None
        done = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)


def extract_release_zip(zip_path: Path, dest_dir: Path) -> Path:
    """解压 zip，返回内含 exe 的应用根目录。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)

    # 优先：小宝蔬菜汇总/小宝蔬菜汇总.exe
    preferred = dest_dir / "小宝蔬菜汇总"
    exe_name = "小宝蔬菜汇总.exe"
    if (preferred / exe_name).is_file():
        return preferred

    # 递归查找
    for p in dest_dir.rglob(exe_name):
        return p.parent

    raise FileNotFoundError(f"zip 内未找到 {exe_name}")


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
    exe = install_root / "小宝蔬菜汇总.exe"
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
