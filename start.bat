@echo off
REM One-click start for Windows: creates a virtual env, installs, runs the app.
cd /d "%~dp0"
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if exist .env ( for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b" )
python -m barndo init
echo Open http://localhost:8000
start http://localhost:8000
python -m barndo serve --port 8000
