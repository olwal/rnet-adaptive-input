@echo off
REM Shim so `rnet <command>` works from cmd.exe, Git Bash, or any shell.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\rnet.ps1" %*
