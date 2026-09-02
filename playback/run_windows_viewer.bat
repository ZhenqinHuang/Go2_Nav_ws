@echo off
cd /d "%~dp0"
python windows_bag_viewer.py .
if errorlevel 1 pause

