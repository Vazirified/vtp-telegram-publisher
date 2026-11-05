@echo off

:: Force the current working directory to match the script's actual location
cd /d "%~dp0"

title VTP - Web Interface
cls

echo ========================================================
echo   VTP - WEB INTERFACE LAUNCHER
echo ========================================================
echo.

if not exist .venv\Scripts\activate.bat goto MISSING_VENV

call .venv\Scripts\activate

:: Older installs don't have the web packages yet
python -c "import fastapi, uvicorn, imageio_ffmpeg" >nul 2>&1
if errorlevel 1 goto INSTALL_PACKAGES
goto LAUNCH_SERVER

:INSTALL_PACKAGES
echo [~] Installing the web interface packages (fastapi, uvicorn, imageio-ffmpeg)...
python -m pip install -r requirements.txt
if errorlevel 1 goto INSTALL_FAILED

:LAUNCH_SERVER
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
