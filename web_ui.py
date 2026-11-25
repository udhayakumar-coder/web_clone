#!/usr/bin/env python3
"""
web_ui.py - Streamlit Web UI for Website Cloner AI
Run: streamlit run web_ui.py
"""

import io
import os
import zipfile
from pathlib import Path
import streamlit as st

from cloner_ai import clone_site

st.set_page_config(page_title="Website Cloner AI", page_icon="🌐", layout="centered")
st.title("🌐 Website Cloner AI")
st.caption("Clone any website for Localhost or GitHub Pages hosting.")

with st.form("clone_form"):
    url = st.text_input("Website URL", placeholder="https://example.com")
    uploaded_html = st.file_uploader(
        "Or upload a saved HTML file (for Cloudflare / Login-protected pages)",
        type=["html", "htm"],
    )

    col1, col2 = st.columns(2)
    with col1:
        provider = st.selectbox("AI Provider", ["gemini", "ollama"])
        mode = st.selectbox("Scrape Mode", ["auto", "playwright", "http"])
    with col2:
        default_model = "gemini-2.5-flash" if provider == "gemini" else "qwen2.5-coder:7b"
        model = st.text_input("Model", value=default_model)
        pages = st.number_input("Max Pages to Clone", min_value=1, max_value=10, value=1)

    api_key = st.text_input(
        "Gemini API Key (leave blank if set in .env)",
        type="password",
        value=os.environ.get("GEMINI_API_KEY", ""),
    )
    output_name = st.text_input("Output Folder Name", value="cloned_site")
    download_assets = st.checkbox("Download images locally into assets/", value=True)
    submitted = st.form_submit_button("Clone Website")

if submitted:
    if not url and not uploaded_html:
        st.error("Please enter a Website URL or upload a saved HTML file.")
    else:
        temp_html = None
        if uploaded_html is not None:
            temp_html = Path("_uploaded_source.html")
            temp_html.write_bytes(uploaded_html.getvalue())

        with st.spinner("Cloning website... Please wait."):
            try:
                out_dir = clone_site(
                    url=url.strip() or None,
                    local_file=temp_html,
                    output_dir=Path(output_name).resolve(),
                    provider=provider,
                    model=model.strip() or None,
                    api_key=api_key.strip() or None,
                    ollama_host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                    mode=mode,
                    pages=int(pages),
                    download_assets=download_assets,
                    max_html_chars=160000,
                    max_css_chars=70000,
                )

                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for p in out_dir.rglob("*"):
                        if p.is_file():
                            zf.write(p, p.relative_to(out_dir))
                buf.seek(0)

                st.success(f"Cloned successfully into `{out_dir}`!")
                st.download_button(
                    label="Download Cloned Site (.zip)",
                    data=buf,
                    file_name=f"{output_name}.zip",
                    mime="application/zip",
                )
                st.code(f"cd {out_dir}\npython -m http.server 8000", language="bash")
            except Exception as exc:
                st.error(f"Cloning failed: {exc}")
            finally:
                if temp_html and temp_html.exists():
                    temp_html.unlink()
