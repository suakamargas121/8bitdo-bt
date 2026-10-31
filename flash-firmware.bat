@echo off
setlocal

cd /d "%~dp0"

echo ==================================================================
echo  8BitDo Ultimate 2C Wireless: XInput Bluetooth Firmware Flasher
echo ==================================================================
echo.

where py >nul 2>nul
if %errorlevel% equ 0 (
    set PY_CMD=py -3.12
) else (
    where python >nul 2>nul
    if %errorlevel% equ 0 (
        set PY_CMD=python
    ) else (
        echo [!] ERROR: Python is not found in PATH.
        echo Please install Python 3.10+ from python.org or Microsoft Store.
        pause
        exit /b 1
    )
)

%PY_CMD% -c "import hid" >nul 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing required 'hidapi' package...
    %PY_CMD% -m pip install hidapi
    if %errorlevel% neq 0 (
        echo [!] ERROR: Failed to install hidapi.
        pause
        exit /b 1
    )
)

%PY_CMD% flash_ultimate2c.py ultimate2c-xbox-windows-rumble.dat %*

if %errorlevel% neq 0 (
    echo.
    echo [*] Command finished with code %errorlevel%.
)

pause
