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
(
  echo @echo off
  echo set "TALLY_URL=%TURL%"
  echo set "TALLY_COMPANY=%TCOMP%"
  echo set "GPT_TALLY_DEFAULT_BANK_LEDGER=%TBANK%"
  echo set "GPT_TALLY_DB=%CD%\data\gpt_tally_v2.sqlite3"
) > scripts\config_env.bat
if not exist data mkdir data
echo.
echo Saved scripts\config_env.bat
echo You can rerun this file whenever the company or port changes.
endlocal
