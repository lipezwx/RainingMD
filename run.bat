@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.13-64 -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)
python main.py %*
