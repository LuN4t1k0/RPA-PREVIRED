@echo off
echo Installing build dependencies...
pip install pyinstaller requests

echo Building PreviredDownloader.exe...
pyinstaller ^
  --onefile ^
  --windowed ^
  --name PreviredDownloader ^
  --add-data "config.py;." ^
  launcher.py

echo.
echo Done. File: dist\PreviredDownloader.exe
pause
