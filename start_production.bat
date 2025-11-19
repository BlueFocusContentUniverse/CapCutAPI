@echo off
REM Production startup script for CapCut API (Windows)

echo Starting CapCut API in production mode...

REM Set default values
if not defined PORT set PORT=9000
if not defined WORKERS set WORKERS=4
if not defined LOG_LEVEL set LOG_LEVEL=info

REM Create logs directory
if not exist logs mkdir logs

REM Start Uvicorn
echo Starting Uvicorn with %WORKERS% workers on port %PORT%
uvicorn main:app --host 0.0.0.0 --port %PORT% --workers %WORKERS% --log-level %LOG_LEVEL%
