@echo off
cd /d "%~dp0"
if exist "leakage_session.rerun.rrd" (
  python -m rerun "leakage_session.rerun.rrd"
) else (
  python windows_bag_viewer.py .
)
if errorlevel 1 pause
