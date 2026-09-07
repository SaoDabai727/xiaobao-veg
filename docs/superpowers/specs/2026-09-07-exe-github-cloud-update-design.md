# 小宝蔬菜汇总 · EXE 打包与 GitHub 云端升级设计

**日期：** 2026-09-07  
**状态：** 已评审待实现  
**仓库（计划）：** 公开仓 `SaoDabai727/xiaobao-veg`

## 背景与目标

现有应用为 Python + CustomTkinter 桌面工具，已用 PyInstaller（`build_exe.spec`）打成 `dist/小宝蔬菜汇总/` 整夹分发。本地尚无 Git 历史；需要：

1. 将源码推送到公开 GitHub 仓库  
2. 通过 GitHub Releases 提供云端升级  
3. 客户端启动检查新版本，用户确认后下载替换并重启  
4. 升级时**保留**用户 `data/`（含 `蔬菜账本.xlsx`）

## 已确认决策

| 项 | 选择 |
|----|------|
| 升级托管 | GitHub Releases（方案 A） |
| 仓库可见性 | 公开 |
| 升级交互 | 启动检查 → 弹窗 → 用户点「立即更新」后下载替换重启 |
| 用户数据 | 升级只替换程序，永不覆盖 `data/` |
| 发版方式 | 推送 `v*` tag 后由 GitHub Actions 自动打包并上传 Release |
| 打包形态 | 保持 onedir：`dist/小宝蔬菜汇总/`，Release 资产为 zip |
| 版本来源 | `app/__init__.py` 中 `__version__`（当前 `1.0.0`） |
| GitHub 账号 | `SaoDabai727`（已 `gh auth login`） |

## 非目标（本期不做）

- 差分更新 / 代码签名 / 私有仓 Token 分发  
- 安装程序（Inno/NSIS）  
- 将账本迁到 `%APPDATA%`（继续使用 exe 旁 `data/`）  
- 强制自动静默升级

## 架构

```
开发机                     GitHub（公开）                 用户电脑
──────                     ─────────────                 ────────
改代码 / 升 __version__
  → commit + tag vX.Y.Z
  → push tag  ──────────►  Actions (windows-latest)
                           · pip + PyInstaller
                           · zip 小宝蔬菜汇总-vX.Y.Z.zip
                           · 挂到该 tag 的 Release
                                              ◄── GET /releases/latest
                                              · 比版本 → 弹窗
                                              · 下载 zip
                                              · 覆盖程序（跳过 data/）
                                              · 重启 exe
```

### 组件

| 组件 | 职责 |
|------|------|
| `app/__init__.py` `__version__` | 客户端版本唯一来源 |
| `app/updater.py`（新建） | 查最新 Release、下载、调度替换与重启 |
| GUI（`app/main.py`） | 启动后后台检查；菜单「检查更新」；弹窗与进度 |
| `.github/workflows/release.yml` | tag `v*` 触发：打包 → zip → 上传 Release |
| 更新辅助脚本（运行时生成） | 主程序退出后拷贝文件并拉起新 exe |
| 可选：`scripts/bump-and-tag.ps1` | 本地改版本、提交、打 tag、push（不负责打包） |

## 版本与 Release 约定

- 版本格式：语义化 `主.次.修订`（如 `1.0.1`）  
- Git tag：`v` + 版本号，必须与 `__version__` 一致（如 `v1.0.1`）  
- 客户端比较：去掉 tag 的 `v` 前缀后与 `__version__` 比较（可用 `packaging.version`）  
- Release 资产名：`xiaobao-veg-vX.Y.Z.zip`（ASCII，避免 Runner 中文文件名损坏；zip 内仍为 `小宝蔬菜汇总/`）  
- zip 内结构：一层根目录 `小宝蔬菜汇总/`，内含 `小宝蔬菜汇总.exe` 与 `_internal/` 等  
- 更新 API（写死）：`https://api.github.com/repos/SaoDabai727/xiaobao-veg/releases/latest`  
- 常量：`GITHUB_OWNER=SaoDabai727`，`GITHUB_REPO=xiaobao-veg`，资产名前缀 `小宝蔬菜汇总-`

## 客户端更新流程

1. 主窗口显示后，后台线程请求 latest Release（超时约 5–8 秒）  
2. 解析 `tag_name` 与 zip 资产下载 URL；无更新或失败则结束（启动检查失败静默）  
3. 有更新：弹窗展示当前版本、新版本、Release body 摘要；按钮「立即更新」「稍后」  
4. 「立即更新」：带进度下载 zip 到临时目录并校验可解压  
5. 解压到临时目录；确认存在预期根目录与 exe  
6. 写出更新脚本后退出主进程；脚本等待进程结束 → 将新文件合并进安装目录（**跳过 `data/`**）→ 启动新 exe → 清理临时文件  
7. 菜单「检查更新」复用同一逻辑；失败时向用户提示「暂时无法连接」等可读信息  

### 数据保护规则

- 覆盖时**禁止**删除或替换安装目录下的 `data/` 目录及其内容  
- Release zip 内即使带有空/示例 `data/`，安装侧也忽略该路径  
- 其它程序文件（exe、`_internal/` 等）允许覆盖  

### 容错

- zip 损坏、根目录名不对、缺少 exe：中止，不改动现网程序  
- 磁盘不足 / 下载中断：提示错误，保留旧版  
- API 限流或无网络：启动检查静默；手动检查给出提示  

## GitHub Actions 发版

触发：`push` tags 匹配 `v*`（或 `v*.*.*`）。

作业概要（`windows-latest`）：

1. checkout  
2. 设置 Python，`pip install -r requirements.txt`  
3. 校验 tag 去掉 `v` 后等于 `app/__init__.py` 的 `__version__`（不一致则失败）  
4. `pyinstaller build_exe.spec --noconfirm`  
5. 将 `dist/小宝蔬菜汇总` 打成 `小宝蔬菜汇总-vX.Y.Z.zip`  
6. 用 `softprops/action-gh-release` 或 `gh release create/upload` 创建/更新该 tag 的 Release，并上传 zip；body 可用 tag 注解或生成变更摘要  

首发：源码入仓后，确认 `__version__=1.0.0`，打 `v1.0.0` 作为基线 Release。

## 仓库落地

1. 完善 `.gitignore`（已有：`dist/`、`build/`、`*.xlsx`、venv 等；确保不提交账本与 OCR 调试大文件）  
2. 首次提交源码与本设计文档  
3. `gh repo create SaoDabai727/xiaobao-veg --public --source=. --remote=origin --push`  
4. 添加 `release.yml` 后再打首个 tag  

客户端**不**嵌入 Token（公开仓即可下载资产）。

## 测试计划

1. 版本比较：低于 / 等于 / 高于 latest；带与不带 `v`  
2. 本地模拟安装：旧目录含账本 → 更新后账本仍在且内容不变  
3. 启动检查与菜单检查路径一致  
4. 推送测试 tag，确认 Actions 产出 zip 并出现在 Release  
5. 真实旧版 exe 升到新版后标题或关于页版本号变化，程序可正常打开账本  

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Actions 上 OCR/onnx 依赖体积大、耗时长 | 接受较长 CI；缓存 pip；失败可重跑 workflow |
| 中文路径 / 资源名在 Runner 上异常 | 工作流与 zip 名保持与现网一致并在 CI 日志中验证 exe 存在 |
| 更新时文件被占用导致拷贝失败 | 更新脚本重试；提示关闭杀毒/占用后重试 |
| GitHub 在部分网络不稳定 | 超时与静默失败；手动检查有明确错误文案 |

## 实现顺序（供后续计划拆解）

1. Git 初始化内容整理、建公开仓并推送  
2. 实现 `updater` + GUI 钩子 + 数据跳过逻辑  
3. 编写 `release.yml`，打 `v1.0.0` 验证 CI  
4. 端到端：改小版本 → tag → 旧包升新包  
