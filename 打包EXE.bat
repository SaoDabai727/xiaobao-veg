@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在打包 小宝蔬菜汇总 ...
pyinstaller build_exe.spec --noconfirm
if errorlevel 1 (
  echo 打包失败
  pause
  exit /b 1
)
echo.
echo 完成：dist\小宝蔬菜汇总\小宝蔬菜汇总.exe
explorer dist\小宝蔬菜汇总
pause
