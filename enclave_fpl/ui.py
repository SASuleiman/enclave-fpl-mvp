"""Streamlit UI for the graphics engine."""

from __future__ import annotations

import base64
import io
import subprocess
import sys
import zipfile

import streamlit as st

from .graphics import CATALOGUE, SIZES, render


@st.cache_resource(show_spinner=False)
def ensure_chromium() -> bool:
    """Streamlit Cloud installs the pip package but not the browser binary.

    Runs at most once per container — cache_resource short-circuits every
    later call, including across sessions.
    """
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        with st.spinner("First run — installing the rendering engine (about a minute)…"):
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"],
                check=False,
            )
        return True


@st.cache_data(ttl=900, show_spinner=False)
def build_card(template: str, ctx: dict, size: str, scale: int) -> bytes:
    return render(template, ctx, size=size, scale=scale)


def _photo_uri(upload) -> str | None:
    if not upload:
        return None
    return f"data:{upload.type};base64,{base64.b64encode(upload.getvalue()).decode()}"


def render_graphics_section(df, gw: int) -> None:
    st.header("🎨 Matchday Graphics")
    st.caption("Brand-locked cards, sized for WhatsApp and Instagram.")

    ensure_chromium()

    left, mid, right = st.columns([2, 1, 1])
    kind = left.selectbox("Card", list(CATALOGUE))
    size = mid.selectbox("Size", list(SIZES), index=0)
    scale = right.select_slider(
        "Quality", [2, 3, 4], value=3,
        help="Supersample factor. 3 is the sweet spot; 4 is slower for little gain.",
    )

    photo = _photo_uri(
        st.file_uploader("Background photo (optional)", type=["jpg", "jpeg", "png"])
    )

    template, ctx = CATALOGUE[kind](df, gw, photo=photo)
    with st.spinner("Rendering…"):
        png = build_card(template, ctx, size, scale)

    st.image(png, use_container_width=True)

    slug = kind.lower().replace(" ", "_")
    st.download_button(
        f"⬇️ Download {kind.lower()}",
        data=png,
        file_name=f"enclave_gw{gw}_{slug}.png",
        mime="image/png",
        use_container_width=True,
    )

    if st.button("📦 Render the full weekly set", use_container_width=True):
        buf = io.BytesIO()
        with st.spinner("Rendering all cards…"), zipfile.ZipFile(buf, "w") as z:
            for name, fn in CATALOGUE.items():
                t, c = fn(df, gw, photo=photo)
                z.writestr(
                    f"gw{gw}_{name.lower().replace(' ', '_')}.png",
                    build_card(t, c, size, scale),
                )
        buf.seek(0)
        st.download_button(
            "⬇️ Download the set (.zip)",
            data=buf,
            file_name=f"enclave_gw{gw}_pack.zip",
            mime="application/zip",
            use_container_width=True,
        )
