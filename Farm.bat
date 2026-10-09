@echo off
REM Compatibility alias: the only panel launcher is FarmPanel.bat.
call "%~dp0FarmPanel.bat" %*
exit /b %errorlevel%
