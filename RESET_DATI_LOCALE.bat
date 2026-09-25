@echo off
setlocal
cd /d "%~dp0"
echo.
echo ============================================
echo   RESET DATI GESTIONALE ORDINI LOCALE
echo ============================================
echo.
echo ATTENZIONE: questa operazione cancella TUTTI i dati locali.
echo Il programma tornera' vergine al prossimo avvio.
echo.
set /p CONFERMA=Scrivi RESET per continuare: 
if /I not "%CONFERMA%"=="RESET" (
    echo Operazione annullata.
    pause
    exit /b 0
)

if exist "dati\gestionale_ordini.sqlite" del /f /q "dati\gestionale_ordini.sqlite"
if exist "dati\gestionale_ordini.sqlite-wal" del /f /q "dati\gestionale_ordini.sqlite-wal"
if exist "dati\gestionale_ordini.sqlite-shm" del /f /q "dati\gestionale_ordini.sqlite-shm"

echo.
echo Reset completato. Il database vuoto verra' ricreato al prossimo avvio.
pause
endlocal
