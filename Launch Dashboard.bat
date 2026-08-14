@echo off
setlocal enabledelayedexpansion
title Retain - Employee Retention Dashboard
cd /d "%~dp0"

echo.
echo   ===========================================================
echo     RETAIN - Employee Retention Intelligence
echo   ===========================================================
echo.

rem --- Find a Python interpreter -----------------------------------------
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo   [X] Python was not found on this computer.
    echo.
    echo       Install Python 3.10 or newer from https://python.org/downloads
    echo       and be sure to tick "Add Python to PATH" during setup.
    echo.
    pause
    exit /b 1
)

rem --- Install dependencies on the first run only -------------------------
if not exist ".setup-complete" (
    echo   First run - installing the libraries this project needs.
    echo   This happens once and takes a couple of minutes.
    echo.
    %PY% -m pip install --quiet --upgrade pip
    %PY% -m pip install --quiet -r requirements.txt
    if errorlevel 1 (
        echo.
        echo   [X] Could not install the required libraries.
        echo       Check your internet connection and try again.
        echo.
        pause
        exit /b 1
    )
    echo done > ".setup-complete"
    echo   Libraries installed.
    echo.
)

rem --- Start the dashboard (it opens the browser itself) ------------------
echo   Starting the dashboard - your browser will open automatically.
echo   The first start also trains the model, which takes about half a minute.
echo.
echo   Leave this window open while you use the dashboard.
echo   Close it, or press CTRL+C, when you are finished.
echo.

rem Any arguments given to this file are passed straight through, so
rem `"Launch Dashboard.bat" --port 9000` or `--no-browser` both work.
%PY% main.py serve %*
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" if not "%EXITCODE%"=="130" (
    echo.
    echo   The dashboard stopped unexpectedly ^(code %EXITCODE%^).
    echo.
    pause
)

endlocal
