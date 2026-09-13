@echo off
setlocal
cd /d "%~dp0\.."
if exist scripts\config_env.bat call scripts\config_env.bat
if not exist .venv\Scripts\python.exe (
  echo GPT-Tally V2 is not installed. Run scripts\install_windows.bat first.
  exit /b 1
)
echo Starting GPT-Tally Local Bridge on http://127.0.0.1:8788
echo Keep this window open while using the hosted dashboard.
.venv\Scripts\python.exe -m gpt_tally_v2.bridge_server
endlocal
