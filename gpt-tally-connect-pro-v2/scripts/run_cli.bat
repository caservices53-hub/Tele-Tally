@echo off
setlocal
cd /d "%~dp0\.."
if exist scripts\config_env.bat call scripts\config_env.bat
call .venv\Scripts\activate
python -m gpt_tally_v2.cli %*
endlocal
