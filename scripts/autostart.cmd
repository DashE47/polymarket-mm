@echo off
rem Shim for the Windows Startup folder - relaunches the paper-trading stack at logon.
rem Install: copy this file to shell:startup (Win+R -> shell:startup -> paste).
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "D:\Claude Code Projects\polymarket-mm\scripts\autostart.ps1"
