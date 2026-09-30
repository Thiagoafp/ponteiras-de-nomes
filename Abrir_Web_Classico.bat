@echo off
cd /d "%~dp0"
start "" http://localhost:8502
python -m streamlit run app_web.py --server.port 8502 --theme.base light --theme.primaryColor "#6c4dff" --theme.backgroundColor "#f4f6fb" --theme.secondaryBackgroundColor "#ffffff" --theme.textColor "#1f2433"
