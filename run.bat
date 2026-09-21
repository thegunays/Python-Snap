@echo off
setlocal DisableDelayedExpansion
pushd "%~dp0" || exit /b 1
set "snapshot_python="
set "snapshot_python_args="
if defined REPO_SNAPSHOT_PYTHON (
    call :probe "%REPO_SNAPSHOT_PYTHON%"
    goto selected
)
call :probe "%~dp0.venv\Scripts\python.exe"
if defined snapshot_python goto selected
call :probe python3
if defined snapshot_python goto selected
call :probe python
if defined snapshot_python goto selected
call :probe py -3
if defined snapshot_python goto selected
call :probe py -3.12

:selected
if not defined snapshot_python (
    >&2 echo Error: Python 3.12 or newer is required. Install Python or set REPO_SNAPSHOT_PYTHON to its executable.
    set "snapshot_status=1"
    goto finish
)
"%snapshot_python%" %snapshot_python_args% -B -m repo_snapshot %*
set "snapshot_status=%errorlevel%"

:finish
if defined snapshot_python (
    "%snapshot_python%" %snapshot_python_args% -c "import sys; sys.exit(not (sys.stdin.isatty() and sys.stdout.isatty()))" 2>nul
    if not errorlevel 1 pause
) else (
    powershell -NoProfile -NonInteractive -Command "exit [int]([Console]::IsInputRedirected -or [Console]::IsOutputRedirected)" 2>nul
    if not errorlevel 1 pause
)
popd
exit /b %snapshot_status%

:probe
"%~1" %2 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if errorlevel 1 exit /b
set "snapshot_python=%~1"
set "snapshot_python_args=%2"
exit /b
