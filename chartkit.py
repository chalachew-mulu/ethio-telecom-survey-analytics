"""chartkit.py - one place to display charts: white background, dark text (also in dark mode / downloads),
plus an on-demand 'Chart image (PNG)' download with a sharp white background."""
import hashlib

import streamlit as st


@st.cache_data(show_spinner=False, max_entries=32)
def _png(spec_json: str):
    try:
        import vl_convert as vlc          # pip install vl-convert-python
        return vlc.vegalite_to_png(spec_json, scale=2.0)
    except Exception:
        return None


def chart(ch, container=None, name="chart"):
    """Show an Altair chart with its own (light) theme; the PNG is built only when requested."""
    tgt = container if container is not None else st
    tgt.altair_chart(ch, width="stretch", theme=None)
    try:
        spec = ch.to_json()
    except Exception:
        return
    key = hashlib.md5(spec.encode()).hexdigest()[:12]
    ss = st.session_state
    if ss.get("png_ready") != key:
        if tgt.button("🖼 Prepare chart image (PNG)", key="pp_" + key):
            ss["png_ready"] = key
            ss["png_bytes"] = _png(spec)
            st.rerun()
    elif ss.get("png_bytes"):
        tgt.download_button("⬇ Download chart image (PNG, white background)", ss["png_bytes"], f"{name}.png", "image/png", key="pd_" + key)
    else:
        tgt.caption("Use the ⋯ menu on the chart to save it as an image.")
