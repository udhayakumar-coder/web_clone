# Website Cloner AI Kit

Clone any website (static HTML, React, Next.js, Vue, or locally saved Cloudflare/login pages) into a clean static HTML/CSS/JS bundle ready for **Localhost** and **GitHub Pages**.

## Files Included
- `cloner_ai.py` — Full CLI agent (Playwright + HTTP + Local HTML + Multi-Page + Localhost Server)
- `web_ui.py` — Streamlit Web UI (paste URL or upload HTML, click Clone, download ZIP)
- `requirements.txt` — Python dependencies
- `setup.bat` / `setup.sh` — One-click installer (installs packages + Playwright Chromium)
- `run_ui.bat` / `run_ui.sh` — One-click Web UI launcher
- `.env.example` — API key template

## Quick Start
1. **Install**
   - Windows: Double-click `setup.bat`
   - Linux/macOS: `chmod +x setup.sh run_ui.sh && ./setup.sh`
2. **Add API Key**
   - Open `.env` and set `GEMINI_API_KEY=...` (or use local Ollama with `--provider ollama`).
3. **Run Web UI**
   - Windows: Double-click `run_ui.bat`
   - Linux/macOS: `./run_ui.sh`
4. **Or Run via CLI**
   ```bash
   # Single page with Playwright + Localhost preview
   python cloner_ai.py --url "https://example.com" --download-assets --serve

   # Multi-page (up to 5 pages)
   python cloner_ai.py --url "https://example.com" --pages 5 --download-assets --serve

   # Cloudflare / Login-protected page (save page in Chrome as Complete HTML first)
   python cloner_ai.py --file "saved_page.html" --serve
   ```
