@echo off
REM Film Search launcher (Windows). Stdlib only, no install.
REM Uses `python` from PATH (no hardcoded interpreter location).
setlocal
if "%FILM_SEARCH_PORT%"=="" set FILM_SEARCH_PORT=43140
python "%~dp0server.py"
