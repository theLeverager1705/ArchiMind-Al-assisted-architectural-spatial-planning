@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt --quiet
echo ArchiMind running at http://localhost:8000
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
