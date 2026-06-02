@echo off
chcp 65001 >nul
echo Installing build dependencies...
python -m pip install -r requirements.txt
python -m pip install pyinstaller
echo.
echo Building installer...
python build_installer.py
pause
