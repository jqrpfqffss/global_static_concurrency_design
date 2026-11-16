@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title ECRA Studio - Local Workbench
set "PYTHONDONTWRITEBYTECODE=1"
if not defined PYTHONHASHSEED set "PYTHONHASHSEED=0"
if exist "%~dp0runtime\python.exe" (
  set "ECRA_PY=%~dp0runtime\python.exe"
) else (
  set "ECRA_PY="
)
if "%~1"=="" goto studio
if "%~1"=="--data-root" goto studio
if "%~1"=="--no-browser" goto studio
if "%~1"=="--port" goto studio
if "%~1"=="--session-file" goto studio
if defined ECRA_PY (
  "%ECRA_PY%" -B "%~dp0run_ecra.py" %*
) else (
  py -3.10 -B "%~dp0run_ecra.py" %*
)
exit /b %ERRORLEVEL%
:studio
if defined ECRA_PY (
  "%ECRA_PY%" -B -m ecra.studio %*
) else (
  py -3.10 -B -m ecra.studio %*
)
set "ECRA_STATUS=%ERRORLEVEL%"
if not "%ECRA_STATUS%"=="0" (
  echo ECRA Studio failed to start. See the error above.
  echo Development: py -3.10 -m pip install -r requirements-studio.txt
  if "%~1"=="" pause
)
exit /b %ECRA_STATUS%
