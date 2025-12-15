@echo off
echo Starting SentryPing Local Server...
echo Open your browser to: http://localhost:8000
echo Press Ctrl+C to stop.
echo.
uvicorn api.index:app --reload
pause
