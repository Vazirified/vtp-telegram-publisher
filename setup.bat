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

title ePlanet Publisher - Autonomous Setup Console
cls

echo ========================================================
echo   ePLANET PUBLISHER - ENVIRONMENT INITIALIZATION
echo ========================================================
echo.

:: Step 1: Check if Python is already active in the PATH
echo [~] Checking for active Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    goto DETECT_LOCAL_PYTHON
) else (
    echo [OK] Python is available in the system PATH.
    goto VENV_STAGE
)

:DETECT_LOCAL_PYTHON
:: Step 2: Check if Python is installed locally but hidden from PATH
echo [!] Python not found in system PATH. Checking localized user paths...
if exist "%USERPROFILE%\AppData\Local\Programs\Python\Python312\python.exe" (
    echo [+] Found existing local Python installation. Injecting environment links...
    set "PATH=%USERPROFILE%\AppData\Local\Programs\Python\Python312\;%USERPROFILE%\AppData\Local\Programs\Python\Python312\Scripts\;%PATH%"
    goto VENV_STAGE
) else (
    goto DOWNLOAD_PYTHON
)

:DOWNLOAD_PYTHON
:: Step 3: Download and install Python completely headlessly
echo [-] Python environment missing from this terminal workspace.
echo [--^>^] Downloading official Python 3.12 installer via curl...
curl -L -o "%TEMP%\python_installer.exe" https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe

if errorlevel 1 (
    echo [ERROR] Network failure: Failed to download Python binaries.
    pause
    exit /b
)

echo [--^>^] Executing silent installation of Python 3.12...
echo       [Processing: ################] Please wait roughly 60s...
start /wait "" "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Shortcuts=0

:: Clean up installer binary
del "%TEMP%\python_installer.exe"

:: Force environment path variables into the live terminal context
set "PATH=%USERPROFILE%\AppData\Local\Programs\Python\Python312\;%USERPROFILE%\AppData\Local\Programs\Python\Python312\Scripts\;%PATH%"

:: Runtime check validation
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Critical failure: Python installation was aborted or paths rejected.
    pause
    exit /b
)
echo [OK] Python 3.12 successfully mounted to the execution run.

:VENV_STAGE
echo.
echo +------------------------------------------------------+
echo :          SANDBOX ENVIRONMENT CONFIGURATION           :
echo +------------------------------------------------------+
echo.

:: Step 4: Build local virtual environment container
if not exist .venv (
    echo [--^>^] Creating localized virtual environment venv...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Core failure: Could not allocate virtual environment container.
        pause
        exit /b
    )
) else (
    echo [i] Existing virtual environment container venv detected.
)

:: Step 5: Activation
echo [--^>^] Activating local execution context...
call .venv\Scripts\activate

:: Step 6: Upgrade package managers inside container
echo [--^>^] Upgrading environment core managers...
python -m pip install --upgrade pip setuptools wheel

:: Step 7: Batch install pipeline requirements (Upgraded to Modern GenAI SDK)
echo [--^>^] Syncing workspace dependencies with remote mirrors...
echo --------------------------------------------------------
pip install requests telethon arabic-reshaper python-bidi Pillow textual google-genai
echo --------------------------------------------------------

if errorlevel 1 (
    echo [ERROR] Direct dependency installation failed.
    pause
    exit /b
)

echo.
echo ========================================================
echo   [SUCCESS] SYSTEM ENVIRONMENT INITIALIZATION COMPLETE
echo ========================================================
echo.
echo   To manually drop into the sandbox later, run:
echo   .venv\Scripts\activate
echo ========================================================
echo.
pause
