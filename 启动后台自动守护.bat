@echo off
cd /d "%~dp0"
python gemini_clash_guardian.py --daemon --interval 180
echo.
pause
