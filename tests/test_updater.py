"""升级模块单测。"""

from __future__ import annotations

from pathlib import Path

from app.updater import (
    format_download_progress,
    is_newer,
    merge_install,
    mirror_download_urls,
    normalize_version,
)


def test_normalize_version() -> None:
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("1.2.3") == "1.2.3"
    assert normalize_version(" V2.0.0 ") == "2.0.0"


def test_is_newer() -> None:
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("1.0.0", "1.0.1")
    assert is_newer("v1.1.0", "1.0.9")


def test_mirror_download_urls() -> None:
    url = "https://github.com/SaoDabai727/xiaobao-veg/releases/download/v1.0.4/xiaobao-veg-v1.0.4.zip"
    urls = mirror_download_urls(url)
    assert urls[-1] == url  # 官方兜底在最后
    assert "ghfast.top" in urls[0]  # 国内镜像优先
    assert any("ghproxy.net" in u for u in urls)
    assert len(urls) == len(set(urls))


def test_format_download_progress() -> None:
    text, ratio = format_download_progress(
        50 * 1024 * 1024, 100 * 1024 * 1024, 2 * 1024 * 1024
    )
    assert "50.0/100.0 MB" in text
    assert "50%" in text
    assert "MB/s" in text
    assert abs(ratio - 0.5) < 1e-6
    text2, ratio2 = format_download_progress(10 * 1024 * 1024, None, 100 * 1024)
    assert "已下 10.0 MB" in text2
    assert "KB/s" in text2
    assert 0 < ratio2 < 1


def test_merge_install_skips_data(tmp_path: Path | None = None) -> None:
    base = tmp_path if tmp_path is not None else Path(__file__).resolve().parent / "_tmp_merge"
    if tmp_path is None:
        if base.exists():
            import shutil

            shutil.rmtree(base)
        base.mkdir(parents=True)

    src = base / "src"
    dst = base / "dst"
    (src / "_internal").mkdir(parents=True)
    (src / "_internal" / "x.txt").write_text("new", encoding="utf-8")
    (src / "蔬菜汇总.exe").write_text("exe-new", encoding="utf-8")
    (src / "data").mkdir()
    (src / "data" / "蔬菜账本.xlsx").write_text("blank", encoding="utf-8")
    (dst / "data").mkdir(parents=True)
    (dst / "data" / "蔬菜账本.xlsx").write_text("USER", encoding="utf-8")
    (dst / "old.txt").write_text("old", encoding="utf-8")
    merge_install(src, dst)
    assert (dst / "data" / "蔬菜账本.xlsx").read_text(encoding="utf-8") == "USER"
    assert (dst / "_internal" / "x.txt").read_text(encoding="utf-8") == "new"
    assert (dst / "蔬菜汇总.exe").read_text(encoding="utf-8") == "exe-new"


if __name__ == "__main__":
    test_normalize_version()
    test_is_newer()
    test_mirror_download_urls()
    test_format_download_progress()
    test_merge_install_skips_data()
    print("ok")
