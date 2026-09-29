@echo off
REM Build ObsOverlay.exe. Thin wrapper around build.ps1 so the build can be
REM started by double-clicking, without changing the PowerShell execution
REM policy machine-wide.
REM
REM Usage:  build.bat                        normal build
REM         build.bat -Clean                 remove previous output first
REM         build.bat -Clean -Installer      also build the setup .exe
REM                                          (needs Inno Setup 6)

setlocal
set "SCRIPT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%build.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Build failed with exit code %EXIT_CODE%.
)

REM Keep the window open when launched from Explorer.
echo.
pause
exit /b %EXIT_CODE%
