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
rem El tar de Windows (bsdtar) escribe rutas con "/"; Compress-Archive de PowerShell 5.1 usa "\" y rompe el zip fuera del Explorador.
del build_out\Burdamix-portable.zip 2>nul
"%SystemRoot%\System32\tar.exe" -a -c -f build_out\Burdamix-portable.zip -C build_out\dist Burdamix || exit /b 1
echo.
echo Listo: build_out\dist\Burdamix\Burdamix.exe  y  build_out\Burdamix-portable.zip
