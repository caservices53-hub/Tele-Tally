@echo off
setlocal
cd /d "%~dp0\.."
if exist scripts\config_env.bat call scripts\config_env.bat
call .venv\Scripts\activate
if "%TALLY_MCP_TOKEN%"=="" (
  echo Set TALLY_MCP_TOKEN before starting remote MCP mode.
  exit /b 2
)
set TALLY_MCP_TRANSPORT=http
python -m gpt_tally_v2.mcp_server
endlocal
