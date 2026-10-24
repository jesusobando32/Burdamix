@echo off
rem Compila Burdamix en build_out\ y crea el zip portable. Uso: build_exe.bat
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    python -m venv .venv || exit /b 1
    .venv\Scripts\python -m pip install --require-hashes -r requirements.lock || exit /b 1
    .venv\Scripts\python -m pip install yt-dlp pyinstaller || exit /b 1
)
.venv\Scripts\python -m PyInstaller Burdamix.spec --noconfirm --distpath build_out\dist --workpath build_out\work || exit /b 1
rem Version portable: un archivo portable.txt junto al .exe hace que todo se guarde en su carpeta.
type nul > build_out\dist\Burdamix\portable.txt
powershell -NoProfile -Command "Compress-Archive -Path build_out\dist\Burdamix -DestinationPath build_out\Burdamix-portable.zip -Force" || exit /b 1
echo.
echo Listo: build_out\dist\Burdamix\Burdamix.exe  y  build_out\Burdamix-portable.zip
