@echo off
setlocal
cd /d "%~dp0\.."
if exist scripts\config_env.bat call scripts\config_env.bat
call .venv\Scripts\activate
set TALLY_MCP_TRANSPORT=stdio
python -m gpt_tally_v2.mcp_server
endlocal
