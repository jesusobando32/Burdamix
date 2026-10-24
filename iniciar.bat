@echo off
rem Doble clic para usar Burdamix. La primera vez instala todo lo necesario (unos minutos).
cd /d "%~dp0"
chcp 65001 >nul
title Burdamix

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python no esta instalado. Se abrira la pagina de descarga.
    echo  Instala Python 3.10 o mas nuevo y MARCA la casilla "Add python.exe to PATH".
    echo  Luego vuelve a abrir este archivo.
    start https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo  Preparando por primera vez, esto puede tardar unos minutos...
    python -m venv .venv
    if errorlevel 1 goto fail
)

".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto fail

".venv\Scripts\python.exe" spotify2mp3.py %*
if "%~1"=="" pause
exit /b %errorlevel%

:fail
echo.
echo  Algo salio mal al instalar. Revisa tu conexion a internet y vuelve a intentarlo.
pause
exit /b 1
