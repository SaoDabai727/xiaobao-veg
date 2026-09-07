# 蔬菜汇总 · 改名与青菜图标设计

## 目标

将产品从「小宝蔬菜汇总」统一改名为「蔬菜汇总」，并配备扁平青绿叶菜（白菜/青菜）应用图标；产出可双击的单文件 exe（v1.0.3）。

## 范围

### 纳入

- 窗口标题、界面品牌文案
- 可执行文件名：`蔬菜汇总.exe`
- 自动更新：zip 内路径与 exe 查找名
- PyInstaller / `打包EXE.bat` / README / Release 工作流中的展示与路径名
- 应用图标：`assets/app.ico`（由青菜 PNG 生成），嵌入 exe + 窗口图标

### 不纳入

- 历史设计/计划文档中的旧名称（不影响运行）
- GitHub 仓库名 `xiaobao-veg`、Release ASCII 资产前缀 `xiaobao-veg-`
- 账本路径逻辑（仍为 exe 旁 `data/`）

## 命名约定

| 用途 | 值 |
|------|-----|
| 产品显示名 | 蔬菜汇总 |
| 窗口标题 | `蔬菜汇总 · 图片转 Excel  v{version}` |
| exe / zip 内目录 | `蔬菜汇总.exe`，zip 根 `蔬菜汇总/` |
| Release 资产（ASCII） | `xiaobao-veg-vX.Y.Z.exe`、`xiaobao-veg-vX.Y.Z.zip` |

## 图标

- 题材：青菜/白菜，扁平矢量风，白底或透明底，小尺寸可辨
- 源图：生成 PNG（建议 1024 或 512 方图）
- 产物：`assets/app.ico`（含 16/32/48/256 等多尺寸）
- 使用：`build_exe.spec` 的 `icon=`；`main.py` 启动时 `iconbitmap` / `wm_iconphoto`

## 自动更新兼容

- `app/updater.py` 中 preferred 路径与 exe 名改为 `蔬菜汇总`
- 旧安装目录若仍为 `小宝蔬菜汇总.exe`，本版起不再作为查找目标（用户需改用新 exe；账本在旁 `data/` 可手动保留）

## 发版

1. `__version__` → `1.0.3`
2. 提交并推送 `main`
3. 打 tag `v1.0.3`，Actions 产出 exe + zip
4. 本地同时保留一份 `蔬菜汇总-v1.0.3.exe` 供直接分发

## 成功标准

- 双击 `蔬菜汇总.exe` 可运行，资源管理器与任务栏显示青菜图标
- 界面可见名称均为「蔬菜汇总」，无「小宝蔬菜汇总」残留（代码与用户可见文案）
- Release 仍可下载 ASCII 名资产；zip 内为 `蔬菜汇总/蔬菜汇总.exe`
