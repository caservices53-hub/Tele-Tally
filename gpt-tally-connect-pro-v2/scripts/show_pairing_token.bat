@echo off
setlocal
cd /d "%~dp0\.."
set "TOKEN_FILE=%CD%\data\bridge_pairing_token.txt"

echo ============================================================
echo GPT-Tally Connect Pro V2 - Pairing Token
echo ============================================================
if exist "%TOKEN_FILE%" (
  type "%TOKEN_FILE%"
) else (
  if exist scripts\config_env.bat call scripts\config_env.bat
  if defined GPT_TALLY_BRIDGE_TOKEN (
    echo %GPT_TALLY_BRIDGE_TOKEN%
  ) else (
    echo No pairing token exists yet.
    echo Run scripts\configure_windows.bat first.
  )
)
echo ============================================================
echo.
pause
endlocal
