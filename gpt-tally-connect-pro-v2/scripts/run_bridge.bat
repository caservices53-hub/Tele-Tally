@echo off
setlocal
cd /d "%~dp0\.."

if not exist .venv\Scripts\python.exe (
  echo GPT-Tally V2 is not installed.
  echo Run scripts\install_windows.bat first.
  echo.
  pause
  exit /b 1
)

if not exist scripts\config_env.bat (
  echo Local configuration is missing.
  echo Running configuration now...
  call scripts\configure_windows.bat
  if errorlevel 1 exit /b 1
)

call scripts\config_env.bat

if not defined GPT_TALLY_BRIDGE_TOKEN (
  echo Pairing token is missing from scripts\config_env.bat.
  echo Run scripts\configure_windows.bat again.
  echo.
  pause
  exit /b 1
)

echo ============================================================
echo GPT-Tally Local Bridge
echo ============================================================
echo URL: http://127.0.0.1:8788
echo Company: %TALLY_COMPANY%
echo Pairing token is configured.
echo Keep this window open while using the hosted dashboard.
echo ============================================================
echo.
.venv\Scripts\python.exe -m gpt_tally_v2.bridge_server

if errorlevel 1 (
  echo.
  echo Local bridge stopped with an error.
  pause
)
endlocal
