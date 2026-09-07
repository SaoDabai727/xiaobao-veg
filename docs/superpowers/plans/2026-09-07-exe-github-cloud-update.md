# EXE + GitHub Cloud Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把小宝蔬菜汇总做成可推送的公开 GitHub 仓，打 `v*` tag 后 Actions 自动打包 Release，客户端能检查更新并在保留 `data/` 的前提下替换程序。

**Architecture:** 纯逻辑放在 `app/updater.py`（查 GitHub Releases API、下载 zip、`--apply-update` 子进程合并安装目录）；GUI 在启动后后台检查并提供「检查更新」菜单项；CI 用 `windows-latest` + 现有 `build_exe.spec` 产出 zip 挂到 Release。

**Tech Stack:** Python 3、urllib、packaging.version、CustomTkinter、PyInstaller、GitHub Actions、`gh`

## Global Constraints

- 公开仓：`SaoDabai727/xiaobao-veg`
- 更新 API：`https://api.github.com/repos/SaoDabai727/xiaobao-veg/releases/latest`
- 版本唯一来源：`app/__init__.py` 的 `__version__`
- tag 格式：`v` + `__version__`（如 `v1.0.0`）
- Release 资产：`小宝蔬菜汇总-vX.Y.Z.zip`，内含根目录 `小宝蔬菜汇总/`
- 升级永不覆盖安装目录下的 `data/`
- 客户端不嵌入 Token
- 启动检查失败静默；手动检查给出中文错误提示

---

## File map

| File | Responsibility |
|------|----------------|
| `app/updater.py` | 版本比较、拉 Release、下载、合并安装、`--apply-update` 入口 |
| `app/main.py` | 启动后台检查、弹窗、更多菜单「检查更新」、标题带版本 |
| `run.py` | 识别 `--apply-update` 参数并走更新入口 |
| `tests/test_updater.py` | 版本比较与合并跳过 `data/` 的单测 |
| `.github/workflows/release.yml` | tag 触发打包上传 |
| `requirements.txt` | 增加 `packaging` |
| `README.md` | 发版与升级说明 |
| `scripts/tag-release.ps1` | 本地校验版本后打 tag 并 push |

---

### Task 1: Updater core + tests

**Files:**
- Create: `app/updater.py`
- Create: `tests/test_updater.py`
- Modify: `requirements.txt`（加入 `packaging>=23.0`）

**Interfaces:**
- Produces:
  - `GITHUB_OWNER: str`, `GITHUB_REPO: str`, `ASSET_PREFIX: str`
  - `normalize_version(tag_or_version: str) -> str`
  - `is_newer(remote: str, local: str) -> bool`
  - `ReleaseInfo` dataclass: `version, tag, notes, asset_name, download_url`
  - `fetch_latest_release(timeout: float = 8.0) -> ReleaseInfo | None`
  - `download_file(url: str, dest: Path, progress_cb=None) -> None`
  - `extract_release_zip(zip_path: Path, dest_dir: Path) -> Path`  # returns app root inside extract
  - `merge_install(src_root: Path, dest_root: Path) -> None`  # skips `data`
  - `spawn_apply_and_exit(src_root: Path, dest_root: Path) -> None`
  - `apply_update_main(argv: list[str]) -> int`
  - `check_for_update() -> ReleaseInfo | None`  # None if no newer

- [ ] **Step 1: Write failing tests** in `tests/test_updater.py`

```python
from __future__ import annotations
from pathlib import Path
from app.updater import is_newer, normalize_version, merge_install

def test_normalize_version():
    assert normalize_version("v1.2.3") == "1.2.3"
    assert normalize_version("1.2.3") == "1.2.3"

def test_is_newer():
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("1.0.0", "1.0.1")
    assert is_newer("v1.1.0", "1.0.9")

def test_merge_install_skips_data(tmp_path: Path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "_internal").mkdir(parents=True)
    (src / "_internal" / "x.txt").write_text("new", encoding="utf-8")
    (src / "小宝蔬菜汇总.exe").write_text("exe-new", encoding="utf-8")
    (src / "data").mkdir()
    (src / "data" / "蔬菜账本.xlsx").write_text("blank", encoding="utf-8")
    (dst / "data").mkdir(parents=True)
    (dst / "data" / "蔬菜账本.xlsx").write_text("USER", encoding="utf-8")
    (dst / "old.txt").write_text("old", encoding="utf-8")
    merge_install(src, dst)
    assert (dst / "data" / "蔬菜账本.xlsx").read_text(encoding="utf-8") == "USER"
    assert (dst / "_internal" / "x.txt").read_text(encoding="utf-8") == "new"
    assert (dst / "小宝蔬菜汇总.exe").read_text(encoding="utf-8") == "exe-new"
```

- [ ] **Step 2: Run tests — expect fail** (module missing)

```bash
set PYTHONPATH=.
python -c "from tests.test_updater import test_is_newer; test_is_newer()"
```

- [ ] **Step 3: Implement `app/updater.py`** with the interfaces above. Use `urllib.request` for API/download; User-Agent `xiaobao-veg-updater`. `merge_install` must never copy a top-level `data` directory. `spawn_apply_and_exit` launches frozen or `sys.executable` + `run.py` with `--apply-update src dest pid`, then `os._exit(0)` after scheduling. `apply_update_main` waits for pid exit (poll), merges, starts dest exe, returns 0.

- [ ] **Step 4: Run tests — expect pass**

```bash
set PYTHONPATH=.
python -c "from tests.test_updater import *; test_normalize_version(); test_is_newer(); from pathlib import Path; import tempfile; ..."
```

Or: `python -m pytest tests/test_updater.py -v` if pytest available; else a small runner in the test file `if __name__ == "__main__"`.

- [ ] **Step 5: Commit**

```bash
git add app/updater.py tests/test_updater.py requirements.txt
git commit -m "feat: add GitHub Releases updater core"
```

---

### Task 2: Wire GUI + run.py entry

**Files:**
- Modify: `run.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `check_for_update`, `ReleaseInfo`, `download_file`, `extract_release_zip`, `spawn_apply_and_exit`, `__version__`
- Produces: UI hooks only

- [ ] **Step 1: Update `run.py`**

```python
"""启动入口（便于 python -m / PyInstaller）。"""
import sys
from app.main import main

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--apply-update":
        from app.updater import apply_update_main
        raise SystemExit(apply_update_main(sys.argv))
    main()
```

- [ ] **Step 2: In `App.__init__`**, after `_reload_sheets()`, schedule `self.after(800, self._schedule_update_check)`. Add version to title: `f"小宝蔬菜汇总 · 图片转 Excel  v{__version__}"`.

- [ ] **Step 3: Add「检查更新」** to `_more_var` values list; handle in `_on_more_action`.

- [ ] **Step 4: Implement methods** `_schedule_update_check`, `_check_update(manual: bool)`, `_prompt_and_install(info: ReleaseInfo)`:
  - background thread calls `check_for_update()` / `fetch_latest_release`
  - manual=True and None/error → messagebox
  - newer → askyesno → download with simple status text → extract → `spawn_apply_and_exit`

- [ ] **Step 5: Smoke run** `python -c "from app.updater import check_for_update; print(check_for_update())"` (may be None before first release)

- [ ] **Step 6: Commit**

```bash
git commit -m "feat: wire startup and menu update checks"
```

---

### Task 3: GitHub Actions release workflow + docs

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `scripts/tag-release.ps1`
- Modify: `README.md`

- [ ] **Step 1: Create workflow** that on `push` tags `v*`:
  - checkout, setup-python 3.12, pip install -r requirements.txt
  - extract version from tag, assert equals `app/__init__.__version__`
  - `pyinstaller build_exe.spec --noconfirm`
  - Compress-Archive / tar zip `dist/小宝蔬菜汇总` → `小宝蔬菜汇总-vX.Y.Z.zip`
  - softprops/action-gh-release@v2 with files: the zip

- [ ] **Step 2: `scripts/tag-release.ps1`** reads `__version__`, creates annotated tag `v$ver`, pushes tag (does not build locally).

- [ ] **Step 3: README** add sections: 云端升级、发版（改版本 → commit → `scripts/tag-release.ps1` 或手动 tag）。

- [ ] **Step 4: Commit**

```bash
git commit -m "ci: auto-build Release zip on version tags"
```

---

### Task 4: Publish repo + baseline v1.0.0

**Files:** all remaining project sources (exclude dist/build/xlsx)

- [ ] **Step 1: Ensure `.gitignore`** covers `dist/`, `build/`, `*.xlsx`, `venv/`, `__pycache__/`, `.venv/`

- [ ] **Step 2: Commit remaining source** (app, tests, specs already partly committed, bats, etc.)

- [ ] **Step 3: Create public repo and push**

```bash
gh repo create SaoDabai727/xiaobao-veg --public --source=. --remote=origin --push
```

- [ ] **Step 4: Create and push tag `v1.0.0`**

```bash
git tag -a v1.0.0 -m "v1.0.0"
git push origin v1.0.0
```

- [ ] **Step 5: Watch Actions** `gh run watch` until success; confirm Release asset exists:

```bash
gh release view v1.0.0
```

- [ ] **Step 6: Verify client can see update API**

```bash
python -c "from app.updater import fetch_latest_release; print(fetch_latest_release())"
```

---

### Task 5: Verification checklist

- [ ] Unit tests for updater pass
- [ ] `fetch_latest_release()` returns 1.0.0 with zip URL after Release ready
- [ ] Manual merge_install test path already covered
- [ ] README documents upgrade + release
- [ ] Report Release URL to user: `https://github.com/SaoDabai727/xiaobao-veg/releases/tag/v1.0.0`
