@echo off
REM Double-click this to launch Narrator. No administrator rights needed.
REM
REM Launches from kokoro-env when it exists next to this file, because the
REM "Check pronunciation" feature needs a library that ships with Kokoro.
REM Qwen3 and edge-tts still work from here -- the app reaches into their
REM own environments by itself when needed (including environments kept in
REM another folder, set under "Set up engines..." in the app).

cd /d "%~dp0"

if exist "kokoro-env\Scripts\activate.bat" (
    call "kokoro-env\Scripts\activate.bat"
) else (
    echo Note: kokoro-env not found next to this file, so this is running
    echo with the system Python. That is normal on a fresh copy: the setup
    echo wizard opens in a moment and can build the engines, or point the app
    echo at engines you already built elsewhere under "Set up engines...".
    echo.
)

REM "python" may be missing from PATH even when Python is installed; the
REM "py" launcher that python.org installs is the fallback.
where python >nul 2>&1
if %errorlevel%==0 (
    python Narrator.py
) else (
    py -3 Narrator.py
)
if errorlevel 1 pause
