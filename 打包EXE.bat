@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打包 蔬菜汇总（单文件 exe）...
pyinstaller build_exe.spec --noconfirm
if errorlevel 1 (
  echo 打包失败
  pause
  exit /b 1
)
echo.
echo 完成：dist\蔬菜汇总.exe
echo 双击即可运行，无需再安装依赖。
explorer /select,"%cd%\dist\蔬菜汇总.exe"
pause
