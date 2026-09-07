# 蔬菜汇总改名与青菜图标 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 产品统一改名为「蔬菜汇总」，嵌入青绿叶菜扁平图标，发版 v1.0.3 单文件 exe。

**Architecture:** 集中常量 `APP_NAME`；生成 PNG→ICO；PyInstaller `name`/`icon` 指向新名与 `assets/app.ico`；updater 查找新 exe 路径；Release 工作流仍产出 ASCII `xiaobao-veg-*` 资产。

**Tech Stack:** Python 3.12、CustomTkinter、Pillow、PyInstaller、GitHub Actions

## Global Constraints

- 显示名 / exe：`蔬菜汇总` / `蔬菜汇总.exe`
- zip 内根目录：`蔬菜汇总/`
- Release ASCII：`xiaobao-veg-vX.Y.Z.exe` / `.zip`
- 图标：`assets/app.ico`（青菜扁平风）
- 版本：`1.0.3`

---

### Task 1: 图标资源

**Files:**
- Create: `assets/app.png`, `assets/app.ico`
- Modify: none

- [ ] **Step 1:** 用 GenerateImage 生成 1:1 青绿叶菜扁平图标 PNG
- [ ] **Step 2:** Pillow 转多尺寸 ICO（16/32/48/256）到 `assets/app.ico`
- [ ] **Step 3:** Commit `assets/`

### Task 2: 改名 + 窗口图标

**Files:**
- Modify: `app/__init__.py`（`__version__=1.0.3`，`APP_NAME="蔬菜汇总"`）
- Modify: `app/main.py`（标题、大标题、icon）
- Modify: `app/updater.py`（exe 名与 zip 路径）
- Modify: `tests/test_updater.py`
- Modify: `build_exe.spec`, `打包EXE.bat`, `.github/workflows/release.yml`, `README.md`

- [ ] **Step 1:** 更新测试中的 exe 名为 `蔬菜汇总.exe`，跑测试
- [ ] **Step 2:** 改代码与打包配置
- [ ] **Step 3:** Commit

### Task 3: 打包发版

- [ ] **Step 1:** `pyinstaller build_exe.spec --noconfirm`
- [ ] **Step 2:** 复制 `dist/蔬菜汇总.exe` → 项目根 `蔬菜汇总-v1.0.3.exe`
- [ ] **Step 3:** 推送 main，打 tag `v1.0.3` 并 push
