@echo off
title Vault Assistant

rem ------------------------------------------------------------------
rem WHY THIS GATE EXISTS (added 2026-08-12): docker compose must run on
rem the SAME side that owns the repo files. When this repo lives inside
rem WSL (its path starts with \\), running compose from the Windows
rem side resolves the relative bind mounts on the wrong side and the
rem app container starts with an EMPTY /app — the "File does not
rem exist: app.py" crash loop. The fix: detect a WSL-hosted repo and
rem delegate the whole job to the WSL side, in this same window.
rem ------------------------------------------------------------------
set "HERE=%~dp0"
if "%HERE:~0,2%"=="\\" (
  echo This repo lives inside WSL - starting from the WSL side,
  echo the side that owns the files. Everything continues below.
  echo.
  wsl.exe --cd "%HERE%" -e bash ./start.sh
  pause
  exit /b
)

rem windows-hosted repo (C:\...): native flow, dialog and folder picker.
rem pushd (not cd) also maps network paths to a drive letter if needed
pushd "%HERE%" || (echo Could not enter the project folder & pause & exit /b 1)

powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; if([System.Windows.Forms.MessageBox]::Show('Start the Vault Assistant?','Vault Assistant',[System.Windows.Forms.MessageBoxButtons]::YesNo,[System.Windows.Forms.MessageBoxIcon]::Question) -ne 'Yes'){exit 1}"
if errorlevel 1 (popd & exit /b 0)

powershell -NoProfile -ExecutionPolicy Bypass -File ".\start.ps1"

popd
pause
