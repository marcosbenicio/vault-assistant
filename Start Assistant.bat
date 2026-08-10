@echo off
title Vault Assistant
rem pushd (not cd): it also maps UNC paths (\\wsl$\...) to a drive
rem letter, so the double-click works even with the repo inside WSL
pushd "%~dp0" || (echo Could not enter the project folder & pause & exit /b 1)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; if([System.Windows.Forms.MessageBox]::Show('Start the Vault Assistant?','Vault Assistant',[System.Windows.Forms.MessageBoxButtons]::YesNo,[System.Windows.Forms.MessageBoxIcon]::Question) -ne 'Yes'){exit 1}"
if errorlevel 1 (popd & exit /b 0)

powershell -NoProfile -ExecutionPolicy Bypass -File ".\start.ps1"

popd
pause
