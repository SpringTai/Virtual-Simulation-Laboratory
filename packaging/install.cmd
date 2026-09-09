@echo off
chcp 65001 >nul
setlocal
echo 正在安装力学虚拟实验室，请稍候……
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if errorlevel 1 (
  echo 安装未完成，请保留上方错误信息。
  pause
  exit /b 1
)
echo 安装完成。请双击桌面上的“力学虚拟实验室”快捷方式。
pause
