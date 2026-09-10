# 蔬菜汇总 · 图片转 Excel

把多张蔬菜清单图片（手写聊天 / 分拣单表格）识别后写入内置 Excel，按菜名合并斤数；月底再导出副本。

## 功能

- 多选图片识别，结果写入内置账本（长期保存）
- 软件内置真实 Excel 表格页（明细 / 汇总），可编辑、保存
- **汇总可直接改斤数**：改完自动记一笔加斤/减斤差额到明细
- **查菜名**：表格上方搜索框，过滤当前页 + 上一条/下一条定位
- **减斤 / 加斤**：可手工调整；图片里写「减/退货/扣」也会识别，**弹窗勾选确认后才扣减**
- **防重复**：左侧显示已入库图片；再次选择同名图会自动跳过
- 添加新图且无重复跳过时**自动开始识别**（有跳过则需手动点「开始识别」）
- 分拣单按行取「菜名 + 最右侧合计」；公斤自动 ×2 成斤
- 自动去掉「硬菜」等品类前缀，过滤客服/分拣单等非菜名
- 导出副本不会清空账本

## 安装（推荐）

1. 从 [Releases](https://github.com/SaoDabai727/xiaobao-veg/releases) 下载 **`xiaobao-veg-setup-v*.exe`**
2. 双击安装（默认 `%LOCALAPPDATA%\蔬菜汇总`，无需管理员）
3. 从开始菜单或桌面打开「蔬菜汇总」

**请勿**从微信/QQ 下载目录直接双击绿色 exe——账本容易写到临时目录或权限不足。

账本固定位置：`%LOCALAPPDATA%\蔬菜汇总\data\蔬菜账本.xlsx`

## 使用步骤

1. 添加图片（无重复跳过时自动识别；有跳过则再点「开始识别」）
2. 左侧上方「已入库图片」会列出已处理过的图，再次选择时会自动跳过
3. 在「汇总」页查看/直接改斤数；也可用「减斤」「加斤」；顶部搜索框快速找菜
4. 月底点「导出副本」另存；也可用「用 Excel 打开」直接打开账本

## 运行（开发）

```bash
pip install -r requirements.txt
python run.py
```

自测：

```bash
set PYTHONPATH=.
python tests/test_logic.py
```

## 打包

```bash
pyinstaller build_exe.spec --noconfirm
```

生成目录版：`dist/蔬菜汇总/`。再用 Inno Setup 编译安装包：

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DMyAppVersion=1.0.12 installer\xiaobao-veg.iss
```

也可双击 `打包EXE.bat`（仅 PyInstaller）。正式发版由 GitHub Actions 自动打 setup。

## 云端升级

- 公开仓库：[SaoDabai727/xiaobao-veg](https://github.com/SaoDabai727/xiaobao-veg)
- 启动后会自动检查 [GitHub Releases](https://github.com/SaoDabai727/xiaobao-veg/releases) 最新版
- 也可在界面「更多…」→「检查更新」
- 更新只替换程序，**保留** `%LOCALAPPDATA%\蔬菜汇总\data\` 账本

## 发版（维护者）

1. 修改 `app/__init__.py` 中的 `__version__`
2. 提交并推送到 `main`
3. 执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/tag-release.ps1
```

4. 等待 Actions 产出：
   - `xiaobao-veg-setup-vX.Y.Z.exe`（**推荐安装包**）
   - `xiaobao-veg-vX.Y.Z.zip`（应用内自动更新）

## 注意

- 不同单据里同一种菜会合并相加（正常汇总）
- 同一张图不要选「仍然追加」，应选覆盖或跳过
- 识别不准时可查看 `%LOCALAPPDATA%\蔬菜汇总\data\last_ocr_debug.txt`
- 首次识别需加载 OCR 模型，略慢属正常
- 若提示账本被占用：先关闭 WPS/Excel 中打开的账本再操作

## 项目结构

```
app/                 # 业务与 GUI
installer/
  xiaobao-veg.iss    # Inno Setup 安装脚本
assets/
  app.ico
data/                # 开发模式账本目录
run.py
build_exe.spec
```
