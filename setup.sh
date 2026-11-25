#!/usr/bin/env bash
set -e
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo "Installing Playwright Chromium browser..."
playwright install chromium
if [ ! -f .env ]; then
  cp .env.example .env
fi
echo "Setup complete! Edit .env to add your GEMINI_API_KEY, then run ./run_ui.sh"
