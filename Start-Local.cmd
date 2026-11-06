@echo off
powershell.exe -NoLogo -NoProfile -File "%~dp0scripts\start-local.ps1" -OpenBrowser
if errorlevel 1 pause
