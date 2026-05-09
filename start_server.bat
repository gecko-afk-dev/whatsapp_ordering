@echo off
cd /d "c:\Users\pc\Desktop\whatsapp_ordering"
echo Starting WhatsApp Ordering Server...
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause