@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================
echo   GESTIONALE ORDINI - VERSIONE PC LOCALE
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PY=python"
    ) else (
        echo Python non trovato.
        echo Installa Python 3.11 o 3.12 da https://www.python.org/downloads/
        echo Durante l'installazione seleziona "Add Python to PATH".
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Primo avvio: creo l'ambiente locale...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo Impossibile creare l'ambiente Python.
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Installazione librerie non completata.
        echo Verifica la connessione Internet e riprova.
        pause
        exit /b 1
    )
) else (
    call ".venv\Scripts\activate.bat"
)

echo Avvio del Gestionale Ordini...
streamlit run app_ordini.py
if errorlevel 1 (
    echo.
    echo Il gestionale si e' chiuso con un errore.
    pause
)
endlocal
