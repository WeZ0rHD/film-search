@echo off
REM Film Search launcher (Windows). Stdlib only, no install.
setlocal
if "%FILM_SEARCH_PORT%"=="" set FILM_SEARCH_PORT=43140
"C:\Python314\python.exe" "%~dp0server.py"
