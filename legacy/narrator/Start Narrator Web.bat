@echo off
REM start_web.bat
REM
REM Launches Narrator's web UI. Put this file in your Narrator folder
REM (next to the narrator/ package folder) and double-click it, or run
REM it from a terminal that's already cd'd into that folder.

python -m narrator web

REM Keeps the window open if something goes wrong (missing dependency,
REM etc.) so the error message doesn't flash and disappear.
if errorlevel 1 (
    echo.
    echo Something went wrong starting the web UI -- see the message above.
    pause
)