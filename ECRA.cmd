@echo off
setlocal DisableDelayedExpansion
cd /d "%~dp0"
title ECRA Studio - Local Workbench
set "ECRA_CONFIG_HOME=%~dp0config"
set "PYTHONDONTWRITEBYTECODE=1"
if exist "%~dp0runtime\python.exe" (
  set "ECRA_PY=%~dp0runtime\python.exe"
  set "ECRA_PORTABLE_ROOT=%~dp0"
) else (
  set "ECRA_PY="
)
if "%~1"=="" goto studio
if "%~1"=="--data-root" goto studio
if "%~1"=="--no-browser" goto studio
if "%~1"=="--port" goto studio
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
if errorlevel 1 (
  echo ECRA Studio failed to start. See the error above.
  echo Development: py -3.10 -m pip install -r requirements-studio.txt
  pause
)
