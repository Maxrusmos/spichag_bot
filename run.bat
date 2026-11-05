@echo off
cd /d "%~dp0"
:loop
.venv\Scripts\python.exe bot.py >> bot.log 2>&1
timeout /t 10 /nobreak >nul
goto loop
