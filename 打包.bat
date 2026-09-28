@echo off
REM ---------------------------------------------------------------------------
REM One-click build. Double-click this file, or run it from a terminal.
REM Equivalent to:  python build.py
REM Arguments are passed through, so "--skip-iss" and "--no-clean" work too.
REM
REM Contents are deliberately ASCII-only and use goto labels instead of
REM parenthesised if-blocks, for two reasons that both bit this file once:
REM
REM   1. cmd.exe reads a .bat with the *current* console code page. This machine
REM      runs 65001 while the system OEM page is 936, so Chinese in a .bat is
REM      mojibake in one of the two cases. All the Chinese progress and error
REM      text lives in build.py instead, where Python talks to the real console
REM      and always gets it right.
REM   2. Backslash is NOT an escape character in cmd - the caret is. Writing
REM      \( text \) inside an if-block makes cmd see real grouping parens, which
REM      closed the block early and let the exit command inside it run
REM      unconditionally, killing the script before build.py ever started.
REM      goto labels have no such failure mode.
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto nopython

python build.py %*
set rc=%errorlevel%
if not "%rc%"=="0" goto failed

echo.
echo [ok] Build finished.
echo      dist\id5_clone\id5_clone.exe         - portable folder build
echo      installer_out\id5_clone-*-setup.exe  - installer
echo.
pause
exit /b 0

:nopython
echo.
echo [!] python not found on PATH.
echo     Install Python 3.12 and add it to PATH, then run this again.
echo     Or drag build.py onto python.exe directly.
echo.
pause
exit /b 1

:failed
echo.
echo [!] Build FAILED with exit code %rc%. The reason is printed above.
echo.
pause
exit /b %rc%
