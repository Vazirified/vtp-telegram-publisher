@echo off

:: Step 0: Auto-elevate execution container to Windows Terminal if available
if not defined WT_SESSION (
    where wt >nul 2>&1
    if %errorlevel% equ 0 (
        start "" wt -p "Command Prompt" cmd /c "%~f0"
        exit /b
    )
)

:: Force the current working directory to match the script's actual location
cd /d "%~dp0"

title ePlanet Publisher - Execution Console
cls

echo ========================================================
echo   ePLANET PUBLISHER - SERVICE LAUNCHER
echo ========================================================
echo.

:: Step 1: Check if the virtual environment exists
if not exist .venv\Scripts\activate.bat goto MISSING_VENV
goto ACTIVATE_VENV

:MISSING_VENV
echo [!] System environment is not initialized.
echo.
set /p setup_choice=[?] Virtual environment not found. Run setup.bat now? [y/n]: 

if /i "%setup_choice%"=="y" goto LAUNCH_SETUP
echo --------------------------------------------------------
echo [i] Exiting launcher.
echo     Please run setup.bat manually.
echo --------------------------------------------------------
pause
exit /b

:LAUNCH_SETUP
echo --------------------------------------------------------
echo [--^>] Handing over execution control to setup.bat...
echo --------------------------------------------------------
call setup.bat

cls
echo ========================================================
echo   ePLANET PUBLISHER - ENVIRONMENT READY
echo ========================================================
echo.
echo   [OK] Setup process has completed successfully.
echo.
echo   [--^>] Please launch run.bat AGAIN to open the application.
echo.
echo ========================================================
pause
exit /b

:ACTIVATE_VENV
:: Step 2: Safe activation of the virtual environment container
echo [--^>] Initializing isolated environment runtime...
call .venv\Scripts\activate
echo [OK] Environment sandbox is live.
echo.

:: Step 3: Interactive Prompt Routing with 5-Second Auto-Timeout
echo [?] Launch master orchestrator (main.py)?
choice /C YN /T 3 /D Y /M "Auto-launching in 3 seconds. Press Y to start now, N to cancel"

:: Check the exit code of the choice command
:: ERRORLEVEL 2 means 'N' was pressed. ERRORLEVEL 1 means 'Y' was pressed or it timed out.
if errorlevel 2 goto MANUAL_MODE
goto LAUNCH_SCRIPT

:LAUNCH_SCRIPT
echo.
echo --------------------------------------------------------
echo [--^>] Launching master pipeline...
echo --------------------------------------------------------
:: Added the -B flag as a secondary safeguard against __pycache__ folders
python -B kernel\main.py
echo --------------------------------------------------------
echo [i] Script execution complete.
pause
exit /b

:MANUAL_MODE
echo.
echo --------------------------------------------------------
echo [i] Bypassing script execution.
echo     Entering manual command line override mode.
echo     Type "deactivate" and close window to exit.
echo --------------------------------------------------------
echo.
cmd /k