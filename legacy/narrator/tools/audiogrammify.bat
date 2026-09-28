@echo off
REM audiogrammify.bat -- drag .wav files onto this on Windows.
REM
REM It just runs audiogrammify.sh, which is the file that actually does
REM the work (and the one to edit if you want to change the recipe).
REM Needs a bash to run it: WSL, or Git Bash if you have Git for Windows
REM installed (both are common if you already have ffmpeg on PATH).

setlocal
set "HERE=%~dp0"

where bash >nul 2>nul
if %errorlevel%==0 goto :run

where wsl >nul 2>nul
if %errorlevel%==0 (
    wsl bash "%HERE%audiogrammify.sh" %*
    goto :done
)

echo No bash found. Install one of:
echo   - WSL            https://learn.microsoft.com/windows/wsl/install
echo   - Git for Windows (includes Git Bash)  https://git-scm.com/download/win
pause
goto :done

:run
bash "%HERE%audiogrammify.sh" %*

:done
pause
