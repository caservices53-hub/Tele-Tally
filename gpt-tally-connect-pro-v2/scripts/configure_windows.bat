@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

echo ============================================================
echo GPT-Tally Connect Pro V2 - Local Configuration
echo ============================================================

set /p TURL=Tally URL [http://localhost:9000]: 
if "%TURL%"=="" set "TURL=http://localhost:9000"
set /p TCOMP=Exact Tally company name: 
set /p TBANK=Default bank ledger (optional): 

if not exist data mkdir data
set "TOKEN_TMP=%CD%\data\.bridge_token_tmp.txt"
set "TOKEN_FILE=%CD%\data\bridge_pairing_token.txt"
set "BTOKEN="

rem Prefer the project virtual environment because install_windows.bat creates it.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import secrets; print(secrets.token_urlsafe(32))" > "%TOKEN_TMP%"
) else (
  where py >nul 2>nul
  if not errorlevel 1 py -c "import secrets; print(secrets.token_urlsafe(32))" > "%TOKEN_TMP%"
)

if exist "%TOKEN_TMP%" set /p BTOKEN=<"%TOKEN_TMP%"
if exist "%TOKEN_TMP%" del /q "%TOKEN_TMP%" >nul 2>nul

rem Fallback for machines where Python token generation could not run.
if not defined BTOKEN (
  for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$a=[guid]::NewGuid().ToString('N'); $b=[guid]::NewGuid().ToString('N'); Write-Output ($a+$b)"`) do if not defined BTOKEN set "BTOKEN=%%i"
)

if not defined BTOKEN (
  echo.
  echo ERROR: Could not generate the local pairing token.
  echo Run scripts\install_windows.bat first and then rerun this file.
  echo.
  pause
  exit /b 1
)

(
  echo @echo off
  echo set "TALLY_URL=%TURL%"
  echo set "TALLY_COMPANY=%TCOMP%"
  echo set "GPT_TALLY_DEFAULT_BANK_LEDGER=%TBANK%"
  echo set "GPT_TALLY_DB=%CD%\data\gpt_tally_v2.sqlite3"
  echo set "GPT_TALLY_BRIDGE_HOST=127.0.0.1"
  echo set "GPT_TALLY_BRIDGE_PORT=8788"
  echo set "GPT_TALLY_BRIDGE_TOKEN=%BTOKEN%"
) > scripts\config_env.bat

> "%TOKEN_FILE%" echo %BTOKEN%

echo.
echo Saved local configuration: scripts\config_env.bat
echo Saved pairing token: data\bridge_pairing_token.txt
echo.
echo ============================================================
echo LOCAL DASHBOARD PAIRING TOKEN
echo ============================================================
echo %BTOKEN%
echo ============================================================
echo Copy the COMPLETE token above into the hosted GPT-Tally dashboard.
echo You can display it again anytime with:
echo     scripts\show_pairing_token.bat
echo.
pause
endlocal
