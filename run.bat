@echo off
:: Starts the VTP terminal + window interface (kernel\main.py) on Windows: double-click run.bat.
:: Offers to run setup.bat when .venv is missing. After each post it asks whether to run again
:: (yes after 5 seconds). Answering N at the first question opens a command prompt inside the
:: virtual environment instead, e.g. to run kernel\publisher.py or kernel\configurator.py by hand.
:: Don't run it together with run-web.bat: the Telegram session allows one program at a time.

:: Step 0: Reopen this script in Windows Terminal when it is installed
if not defined WT_SESSION (
    where wt >nul 2>&1
    if %errorlevel% equ 0 (
        start "" wt -p "Command Prompt" cmd /c "%~f0"
        exit /b
    )
)

:: Run from the project folder, wherever the script is called from
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
:: Step 2: Activate the virtual environment
echo [--^>] Initializing isolated environment runtime...
call .venv\Scripts\activate
echo [OK] Environment sandbox is live.
echo.

:: Step 3: Ask whether to start main.py; no answer within 3 seconds means yes
echo [?] Launch master orchestrator (main.py)?
choice /C YN /T 3 /D Y /M "Auto-launching in 3 seconds. Press Y to start now, N to cancel"

:: Check the exit code of the choice command
:: ERRORLEVEL 2 means 'N' was pressed.
if errorlevel 2 goto MANUAL_MODE
goto LAUNCH_SCRIPT

:LAUNCH_SCRIPT
echo.
echo --------------------------------------------------------
echo [--^>] Launching master pipeline...
echo --------------------------------------------------------
:: -B: don't write __pycache__ folders (main.py also turns this off itself)
python -B kernel\main.py
echo --------------------------------------------------------
echo [i] Script execution complete.
echo --------------------------------------------------------
echo.

:: Run main.py again (one post per run) unless the user presses N within 5 seconds
choice /C YN /T 5 /D Y /M "Auto-relaunching in 5 seconds. Press Y to run again, N to exit"
if errorlevel 2 goto END_SCRIPT
goto LAUNCH_SCRIPT

:END_SCRIPT
echo.
echo [i] Exiting launcher...
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