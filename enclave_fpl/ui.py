"""Streamlit UI for the graphics engine."""

from __future__ import annotations

import base64
import io
import zipfile

import streamlit as st

from .browser import BrowserUnavailable, ensure_chromium
from .graphics import CATALOGUE, SIZES, render


@st.cache_resource(show_spinner=False)
def _engine_status() -> tuple[bool, str]:
    """Cached once per container. Returns (ready, detail-or-reason).

    Returns a tuple rather than raising so a failure is cached as a failure —
    the caller renders an explanation instead of a stack trace, and the rest
    of the dashboard keeps working.
    """
    try:
        with st.spinner("First run — setting up the rendering engine (up to a minute)…"):
            return True, ensure_chromium()
    except BrowserUnavailable as e:
        return False, str(e)


@st.cache_data(ttl=900, show_spinner=False)
def build_card(template: str, ctx: dict, size: str, scale: int) -> bytes:
    return render(template, ctx, size=size, scale=scale)


def _photo_uri(upload) -> str | None:
    if not upload:
        return None
    return f"data:{upload.type};base64,{base64.b64encode(upload.getvalue()).decode()}"


def render_graphics_section(df, gw: int) -> None:
    st.header("🎨 Matchday Graphics")

    ready, detail = _engine_status()
    if not ready:
        st.error("The graphics engine isn't available on this host.")
        with st.expander("What went wrong", expanded=True):
            st.code(detail, language="text")
        if st.button("Retry setup"):
            _engine_status.clear()
            st.rerun()
        return

    st.caption("Brand-locked cards, sized for WhatsApp and Instagram.")

    left, mid, right = st.columns([2, 1, 1])
    kind = left.selectbox("Card", list(CATALOGUE))
    size = mid.selectbox("Size", list(SIZES), index=0)
    scale = right.select_slider(
        "Quality", [2, 3, 4], value=3,
        help="Supersample factor. 3 is the sweet spot. Drop to 2 if the host is memory-tight.",
    )

    photo = _photo_uri(
        st.file_uploader("Background photo (optional)", type=["jpg", "jpeg", "png"])
    )

    template, ctx = CATALOGUE[kind](df, gw, photo=photo)

    try:
        with st.spinner("Rendering…"):
            png = build_card(template, ctx, size, scale)
    except Exception as e:  # noqa: BLE001
        st.error(f"Render failed: {type(e).__name__}: {e}")
        st.caption("If this mentions memory or a closed target, try quality 2.")
        return

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
        try:
            with st.spinner("Rendering all cards…"), zipfile.ZipFile(buf, "w") as z:
                for name, fn in CATALOGUE.items():
                    t, c = fn(df, gw, photo=photo)
                    z.writestr(
                        f"gw{gw}_{name.lower().replace(' ', '_')}.png",
                        build_card(t, c, size, scale),
                    )
        except Exception as e:  # noqa: BLE001
            st.error(f"Batch render failed: {type(e).__name__}: {e}")
            return
        buf.seek(0)
        st.download_button(
            "⬇️ Download the set (.zip)",
            data=buf,
            file_name=f"enclave_gw{gw}_pack.zip",
            mime="application/zip",
            use_container_width=True,
        )
