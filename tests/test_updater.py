"""升级模块单测。"""

from __future__ import annotations

from pathlib import Path

from app.updater import is_newer, merge_install, normalize_version


def test_normalize_version() -> None:
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("1.2.3") == "1.2.3"
    assert normalize_version(" V2.0.0 ") == "2.0.0"


def test_is_newer() -> None:
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("1.0.0", "1.0.1")
    assert is_newer("v1.1.0", "1.0.9")


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
    test_merge_install_skips_data()
    print("ok")
