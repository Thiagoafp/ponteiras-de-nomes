@echo off
cd /d "%~dp0"
start "" http://localhost:8501
python -m streamlit run app_studio.py --server.port 8501
