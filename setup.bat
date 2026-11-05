@echo off
:: VTP setup for Windows: double-click setup.bat once (run.bat also offers to start it).
:: - Uses the Python on PATH, else %LOCALAPPDATA%\Programs\Python\Python312, else downloads
::   Python 3.12.3 from python.org and installs it for this user (no admin rights needed).
:: - Creates the virtual environment in .venv (kept if it exists) and installs requirements.txt.
:: Headlines need no extra system library on Windows: kernel\lib holds the FriBiDi DLL that
:: Pillow's Raqm text layout uses, and imageio-ffmpeg brings ffmpeg for video posts.
:: Afterwards start VTP with run-web.bat (web interface) or run.bat (terminal + window interface).

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
:: Step 3: Download Python 3.12 and install it silently for the current user, added to PATH
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

:: The installer's PATH change only reaches new windows; add it to this one by hand
set "PATH=%USERPROFILE%\AppData\Local\Programs\Python\Python312\;%USERPROFILE%\AppData\Local\Programs\Python\Python312\Scripts\;%PATH%"

:: Check that the installed Python runs
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

:: Step 4: Create the virtual environment in .venv, unless it already exists
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

:: Step 6: Upgrade pip and its build tools inside the virtual environment
echo [--^>^] Upgrading environment core managers...
python -m pip install --upgrade pip setuptools wheel

:: Step 7: Install the Python packages listed in requirements.txt
echo [--^>^] Syncing workspace dependencies with remote mirrors...
echo --------------------------------------------------------
pip install -r requirements.txt
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
