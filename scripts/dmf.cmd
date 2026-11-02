@echo off
if not "%~1"=="start" exit /b 2
if not "%~2"=="" exit /b 2
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0Launch-DMFPulse.ps1"
exit /b %ERRORLEVEL%
