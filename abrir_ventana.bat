@echo off
rem Abre la ventana de Burdamix desde el codigo (sin compilar). Doble clic para usarlo.
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0gui_app.py"
) else (
    start "" pythonw "%~dp0gui_app.py"
)
