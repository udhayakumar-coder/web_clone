#!/usr/bin/env python3
"""
cloner_ai.py - Full-Featured Website Cloner AI Agent
----------------------------------------------------
Supports:
  - Playwright headless Chromium rendering (React, Next.js, Vue, Angular, SPAs)
  - Fast HTTP fallback (BeautifulSoup)
  - Local saved HTML file mode (--file) for Cloudflare/login-protected pages
  - Multi-page same-origin crawling (--pages N)
  - Local asset downloading (--download-assets) for offline & GitHub Pages
  - Google Gemini (google-genai) & Local Ollama
  - Built-in Localhost HTTP server (--serve)
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: 'beautifulsoup4' is required. Run: pip install -r requirements.txt")
    sys.exit(1)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

SYSTEM_PROMPT = """You are an expert Frontend Architect and Website Cloner AI.
Your task is to reconstruct the given webpage's rendered HTML and CSS into a clean,
faithful, responsive, production-ready static page for Localhost and GitHub Pages.

Rules:
1. Preserve the visual layout, sections, navigation, typography, color palette, cards,
   buttons, forms (UI), and footer as closely as possible.
2. Output ONLY raw valid JSON with three string keys (no markdown fences):
   - "html": Complete HTML5 document linking to "styles.css" and "script.js"
   - "styles_css": Complete responsive CSS3 stylesheet (preserve/merge layout & theme)
   - "script_js": Clean vanilla JS for interactive UI (mobile menu, tabs, accordions, smooth scroll)
3. Use relative paths ("styles.css", "script.js", "assets/...", or sibling ".html" files)
   so it works on both http://localhost:PORT and https://<user>.github.io/<repo>/.
4. Keep external image/font URLs intact if not downloaded locally, and ensure every <img>
   has an alt attribute.
"""


def load_env_file(env_path: Path) -> None:
    """Load key=value pairs from .env if present."""
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def fetch_http_text(url: str, timeout: int = 20) -> Tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()
        charset = resp.headers.get_content_charset() or "utf-8"
        raw = resp.read()
        try:
            return raw.decode(charset, errors="replace"), final_url
        except LookupError:
            return raw.decode("utf-8", errors="replace"), final_url


def fetch_with_playwright(url: str, timeout_ms: int = 35000) -> Tuple[str, str]:
    """Render page using headless Chromium via Playwright (handles React/Next/SPA)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        # Scroll down to trigger lazy-loaded sections/images
        page.evaluate(
            """async () => {
                for (let y = 0; y < document.body.scrollHeight; y += 600) {
                    window.scrollTo(0, y);
                    await new Promise(r => setTimeout(r, 150));
                }
                window.scrollTo(0, 0);
            }"""
        )
        page.wait_for_timeout(800)
        html = page.content()
        final_url = page.url
        browser.close()
        return html, final_url


def fetch_page_html(url: Optional[str], local_file: Optional[Path], mode: str) -> Tuple[str, str]:
    """Fetch HTML using local file, Playwright, or HTTP fallback."""
    if local_file is not None:
        html = local_file.read_text(encoding="utf-8", errors="replace")
        return html, url or f"file://{local_file.resolve()}"

    if not url:
        raise ValueError("Either --url or --file must be provided.")

    if mode in ("auto", "playwright"):
        try:
            return fetch_with_playwright(url)
        except ImportError:
            if mode == "playwright":
                raise RuntimeError(
                    "Playwright not installed. Run: pip install playwright && playwright install chromium"
                )
            print("  [!] Playwright not available, falling back to HTTP mode...")
        except Exception as exc:
            if mode == "playwright":
                raise
            print(f"  [!] Playwright failed ({exc}), falling back to HTTP mode...")

    return fetch_http_text(url)


def download_binary(url: str, dest: Path, timeout: int = 15) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def slug_for_url(url: str, root_url: str) -> str:
    """Convert an internal URL to a clean static .html filename."""
    p_url = urllib.parse.urlparse(url)
    p_root = urllib.parse.urlparse(root_url)
    if p_url.path in ("", "/", p_root.path) and not p_url.query:
        return "index.html"
    path = p_url.path.strip("/")
    if not path:
        return "index.html"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", path).strip("_") or "page"
    if not slug.endswith(".html"):
        slug += ".html"
    return slug


def extract_context(
    html_raw: str,
    final_url: str,
    output_dir: Path,
    download_assets: bool,
    max_html_chars: int,
    max_css_chars: int,
) -> Tuple[Dict[str, str], List[str]]:
    """Extract cleaned HTML, CSS, assets, and same-origin internal links."""
    soup = BeautifulSoup(html_raw, "html.parser")
    base_parsed = urllib.parse.urlparse(final_url)
    assets_dir = output_dir / "assets"
    downloaded_count = 0

    internal_links: List[str] = []
    seen_links: Set[str] = {final_url.rstrip("/")}

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_link = urllib.parse.urljoin(final_url, href).split("#")[0]
        parsed = urllib.parse.urlparse(abs_link)
        if parsed.scheme in ("http", "https") and parsed.netloc == base_parsed.netloc:
            norm = abs_link.rstrip("/")
            if norm not in seen_links:
                seen_links.add(norm)
                internal_links.append(abs_link)

    for tag_name, attr in [("img", "src"), ("link", "href"), ("script", "src")]:
        for tag in soup.find_all(tag_name):
            val = tag.get(attr)
            if not val or val.startswith(("data:", "javascript:", "mailto:", "#")):
                continue
            abs_url = urllib.parse.urljoin(final_url, val)
            if download_assets and tag_name == "img" and downloaded_count < 40:
                parsed = urllib.parse.urlparse(abs_url)
                fname = Path(parsed.path).name or f"img_{downloaded_count}.png"
                fname = re.sub(r"[^a-zA-Z0-9._-]", "_", fname)
                if "." not in fname:
                    fname += ".png"
                local_path = assets_dir / f"{downloaded_count}_{fname}"
                if download_binary(abs_url, local_path):
                    tag[attr] = f"assets/{local_path.name}"
                    downloaded_count += 1
                    continue
            tag[attr] = abs_url

    css_chunks: List[str] = []
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            css_chunks.append(style_tag.string.strip())

    for link_tag in soup.find_all("link", rel=lambda r: r and "stylesheet" in r):
        href = link_tag.get("href")
        if href and href.startswith(("http://", "https://")):
            try:
                css_text, _ = fetch_http_text(href, timeout=10)
                css_chunks.append(f"/* {href} */\n{css_text}")
            except Exception:
                pass
        if sum(len(c) for c in css_chunks) >= max_css_chars:
            break

    for script_tag in soup.find_all("script"):
        if not script_tag.get("src"):
            script_tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else "Cloned Website"
    cleaned_html = soup.prettify()[:max_html_chars]
    combined_css = "\n\n".join(css_chunks)[:max_css_chars]

    return {
        "url": final_url,
        "title": title,
        "html": cleaned_html,
        "css": combined_css,
    }, internal_links


def call_gemini(prompt: str, model: str, api_key: Optional[str]) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("Error: 'google-genai' is required. Run: pip install -r requirements.txt")
        sys.exit(1)

    key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY. Set it in .env, environment, or --api-key.")

    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    return response.text or ""


def call_ollama(prompt: str, model: str, host: str) -> str:
    endpoint = f"{host.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        return body.get("response", "")


def parse_ai_json(raw_text: str) -> Dict[str, str]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    parsed = json.loads(cleaned)
    for key in ("html", "styles_css", "script_js"):
        if key not in parsed or not isinstance(parsed[key], str):
            raise ValueError(f"Missing key '{key}' in AI JSON output.")
    return parsed


def clone_site(
    url: Optional[str],
    local_file: Optional[Path],
    output_dir: Path,
    provider: str,
    model: Optional[str],
    api_key: Optional[str],
    ollama_host: str,
    mode: str,
    pages: int,
    download_assets: bool,
    max_html_chars: int,
    max_css_chars: int,
) -> Path:
    """Main cloning pipeline. Returns the output directory Path."""
    load_env_file(Path(__file__).parent / ".env")
    output_dir.mkdir(parents=True, exist_ok=True)
    chosen_model = model or ("gemini-2.5-flash" if provider == "gemini" else "qwen2.5-coder:7b")

    queue: List[str] = [url] if url else []
    visited: Set[str] = set()
    all_css: List[str] = []
    all_js: List[str] = []
    root_url = url or "local_file"

    page_count = 0
    while (queue or local_file is not None) and page_count < pages:
        current_url = queue.pop(0) if queue else None
        if current_url and current_url.rstrip("/") in visited:
            continue
        if current_url:
            visited.add(current_url.rstrip("/"))

        print(f"[{page_count + 1}/{pages}] Fetching: {current_url or local_file}")
        html_raw, final_url = fetch_page_html(current_url, local_file, mode)
        local_file = None  # Only used for first iteration
        if page_count == 0:
            root_url = final_url

        context, internal_links = extract_context(
            html_raw=html_raw,
            final_url=final_url,
            output_dir=output_dir,
            download_assets=download_assets,
            max_html_chars=max_html_chars,
            max_css_chars=max_css_chars,
        )

        for link in internal_links:
            if link.rstrip("/") not in visited and link not in queue and len(visited) + len(queue) < pages * 2:
                queue.append(link)

        filename = "index.html" if page_count == 0 else slug_for_url(final_url, root_url)
        prompt = (
            f"Clone this page into clean static HTML/CSS/JS.\n"
            f"Target URL: {context['url']}\n"
            f"Output Filename: {filename}\n"
            f"Title: {context['title']}\n\n"
            f"--- HTML ---\n{context['html']}\n\n"
            f"--- CSS ---\n{context['css']}\n"
        )

        print(f"    Generating with {provider} ({chosen_model})...")
        raw_ai = (
            call_gemini(prompt, chosen_model, api_key)
            if provider == "gemini"
            else call_ollama(prompt, chosen_model, ollama_host)
        )
        result = parse_ai_json(raw_ai)

        (output_dir / filename).write_text(result["html"], encoding="utf-8")
        all_css.append(f"/* === {filename} === */\n{result['styles_css']}")
        all_js.append(f"// === {filename} ===\n{result['script_js']}")
        page_count += 1

    (output_dir / "styles.css").write_text("\n\n".join(all_css), encoding="utf-8")
    (output_dir / "script.js").write_text("\n\n".join(all_js), encoding="utf-8")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")

    readme = f"""# Cloned Website Project

Source: {root_url}
Pages cloned: {page_count}

## Localhost Hosting
```bash
cd "{output_dir.name}"
python3 -m http.server 8000
```
Open: http://localhost:8000

## GitHub Pages Hosting
```bash
git init
git add .
git commit -m "Deploy cloned website"
git branch -M main
git remote add origin https://github.com/<USERNAME>/<REPO>.git
git push -u origin main
```
Enable GitHub Pages in **Repo Settings -> Pages -> Branch: `main` (`/root`)**.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return output_dir


def serve_locally(directory: Path, port: int) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"\nLocalhost running at: http://localhost:{port}  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Website Cloner AI (Localhost & GitHub Pages)")
    parser.add_argument("--url", default=None, help="Website URL to clone")
    parser.add_argument("--file", default=None, help="Local saved HTML file (for Cloudflare/login sites)")
    parser.add_argument("--output", default="cloned_site", help="Output folder (default: cloned_site)")
    parser.add_argument("--provider", choices=["gemini", "ollama"], default="gemini")
    parser.add_argument("--model", default=None, help="Model override")
    parser.add_argument("--api-key", default=None, help="Gemini API key")
    parser.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    parser.add_argument("--mode", choices=["auto", "playwright", "http"], default="auto")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to crawl (default: 1)")
    parser.add_argument("--download-assets", action="store_true", help="Download images to assets/")
    parser.add_argument("--max-html-chars", type=int, default=160000)
    parser.add_argument("--max-css-chars", type=int, default=70000)
    parser.add_argument("--serve", action="store_true", help="Start localhost preview server")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    local_path = Path(args.file).resolve() if args.file else None
    out = clone_site(
        url=args.url,
        local_file=local_path,
        output_dir=Path(args.output).resolve(),
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        ollama_host=args.ollama_host,
        mode=args.mode,
        pages=max(1, args.pages),
        download_assets=args.download_assets,
        max_html_chars=args.max_html_chars,
        max_css_chars=args.max_css_chars,
    )
    print(f"\nSuccess! Cloned site ready in: {out}")
    if args.serve:
        serve_locally(out, args.port)


if __name__ == "__main__":
    main()
