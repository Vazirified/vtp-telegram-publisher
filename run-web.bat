@echo off
:: Starts the VTP web interface on Windows: double-click, or run-web.bat [--port 9000] [--no-browser]
:: Serves the page at http://127.0.0.1:8765/ (this PC only) and opens it in the default browser.
:: Stop it with Ctrl+C. Needs .venv from setup.bat; missing web packages are installed here.
:: Don't run it together with run.bat: the Telegram session allows one program at a time.

:: Run from the project folder, wherever the script is called from
cd /d "%~dp0"

title VTP - Web Interface
cls

echo ========================================================
echo   VTP - WEB INTERFACE LAUNCHER
echo ========================================================
echo.

if not exist .venv\Scripts\activate.bat goto MISSING_VENV

call .venv\Scripts\activate

:: Virtual environments made before the web interface or video posts lack these packages
python -c "import fastapi, uvicorn, imageio_ffmpeg" >nul 2>&1
if errorlevel 1 goto INSTALL_PACKAGES
goto LAUNCH_SERVER

:INSTALL_PACKAGES
echo [~] Installing the web interface packages (fastapi, uvicorn, imageio-ffmpeg)...
python -m pip install -r requirements.txt
if errorlevel 1 goto INSTALL_FAILED

:LAUNCH_SERVER
:: -B: don't write __pycache__ folders. Arguments (--port, --no-browser) are passed on.
python -B kernel\webapp.py %*
echo.
echo [i] Web server stopped.
pause
exit /b

:INSTALL_FAILED
echo [!] Package installation failed. Check the messages above.
pause
exit /b

:MISSING_VENV
echo [!] Virtual environment not found. Run setup.bat first.
pause
exit /b
