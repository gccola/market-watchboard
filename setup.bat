@echo off
chcp 65001 >nul
if exist "dist\行情看板安装包.exe" (
  start "" "dist\行情看板安装包.exe"
) else (
  echo Installer not found. Building first...
  call build.bat
)
