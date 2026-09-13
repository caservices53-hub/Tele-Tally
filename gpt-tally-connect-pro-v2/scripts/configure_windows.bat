@echo off
setlocal
cd /d "%~dp0\.."
echo ============================================================
echo GPT-Tally Connect Pro V2 - Local Configuration
echo ============================================================
set /p TURL=Tally URL [http://localhost:9000]: 
if "%TURL%"=="" set "TURL=http://localhost:9000"
set /p TCOMP=Exact Tally company name: 
set /p TBANK=Default bank ledger (optional): 
for /f %%i in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N')"') do set "BTOKEN=%%i"
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
if not exist data mkdir data
echo.
echo Saved scripts\config_env.bat
echo.
echo ============================================================
echo LOCAL DASHBOARD PAIRING TOKEN
echo %BTOKEN%
echo ============================================================
echo Copy this token into the hosted GPT-Tally dashboard.
echo The token is only for this PC and is not uploaded automatically.
echo.
endlocal
