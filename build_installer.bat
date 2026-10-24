@echo off
rem Crea el instalador build_out\Burdamix-Setup.exe. Primero hay que ejecutar build_exe.bat. Necesita Inno Setup 6:
rem   winget install JRSoftware.InnoSetup
setlocal
cd /d "%~dp0"
if not exist build_out\dist\Burdamix\Burdamix.exe (
    echo Primero ejecuta build_exe.bat
    exit /b 1
)
set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
    if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
    echo No encuentro Inno Setup 6. Instalalo con: winget install JRSoftware.InnoSetup
    exit /b 1
)
"%ISCC%" installer.iss || exit /b 1
echo.
echo Listo: build_out\Burdamix-Setup.exe
