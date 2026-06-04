@echo off
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
echo [i] Exiting launcher. Please run setup.bat manually.
echo --------------------------------------------------------
pause
exit /b

:LAUNCH_SETUP
echo --------------------------------------------------------
echo [-->] Handing over execution control to setup.bat...
echo --------------------------------------------------------
call setup.bat

:: This section catches control after setup.bat finishes
cls
echo ========================================================
echo   ePLANET PUBLISHER - ENVIRONMENT READY
echo ========================================================
echo.
echo   [OK] Setup process has completed successfully.
echo.
echo   [-->] Please launch run.bat AGAIN to open the application.
echo.
echo ========================================================
pause
exit /b

:ACTIVATE_VENV
:: Step 2: Safe activation of the virtual environment container
echo [-->] Initializing isolated environment runtime...
call .venv\Scripts\activate
echo [OK] Environment sandbox is live.
echo.

:: Step 3: Interactive Prompt Routing
set /p choice=[?] Launch orchestrator interface script? [y/n]: 

if /i "%choice%"=="y" goto LAUNCH_SCRIPT
goto MANUAL_MODE

:LAUNCH_SCRIPT
echo --------------------------------------------------------
echo [-->] Launching interface engine...
echo --------------------------------------------------------
python Kernel\orchestrator.py
echo --------------------------------------------------------
echo [i] Script execution complete.
pause
exit /b

:MANUAL_MODE
echo --------------------------------------------------------
echo [i] Bypassing script execution.
echo     Entering manual command line override mode.
echo     Type "deactivate" and close window to exit.
echo --------------------------------------------------------
echo.
cmd /k