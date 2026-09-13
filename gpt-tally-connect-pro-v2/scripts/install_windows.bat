@echo off
setlocal
cd /d "%~dp0\.."
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher not found. Install Python 3.11 or newer first.
  exit /b 1
)
py -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e ".[all]"
if errorlevel 1 exit /b 1
if not exist data mkdir data
call scripts\configure_windows.bat
echo.
echo Installed successfully.
echo Keep TallyPrime open with HTTP server enabled before running Tally commands.
echo Test connection with: scripts\run_cli.bat status
endlocal
