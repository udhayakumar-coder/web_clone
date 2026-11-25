@echo off
echo Installing Python dependencies...
pip install -r requirements.txt
echo Installing Playwright Chromium browser (for React/Next.js/SPA websites)...
playwright install chromium
if not exist .env copy .env.example .env
echo.
echo Setup complete! Edit .env to add your GEMINI_API_KEY, then run run_ui.bat.
pause
