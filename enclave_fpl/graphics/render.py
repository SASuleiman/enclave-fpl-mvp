"""
Enclave FPL — graphics renderer.

Renders Jinja/HTML cards through headless Chromium at 2-3x, then downsamples
with Lanczos. The supersample step is what makes the type look printed rather
than screenshotted; skip it and Anton's thin counters go crunchy.

One browser is launched per process and reused, so the second card onward
renders in roughly 150ms.
"""

from __future__ import annotations

import atexit
import base64
import io
import pathlib
import threading
from concurrent.futures import ThreadPoolExecutor

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).parent
STATIC = ROOT / "static"
FONTS = STATIC / "fonts"

# Instagram / WhatsApp friendly presets
SIZES = {
    "portrait": (1080, 1350),   # feed post — the default
    "square":   (1080, 1080),
    "story":    (1080, 1920),
    "wide":     (1600, 900),    # group-chat preview / Twitter
}

# --------------------------------------------------------------------------
# Browser thread
#
# Playwright's sync API is greenlet-based and pinned to the thread that
# started it. Streamlit executes every rerun in a NEW ScriptRunner thread and
# lets the previous one exit, so a browser cached in module globals becomes
# unreachable the moment the thread that made it goes away:
#
#     greenlet.error: cannot switch to a different thread (which happens to
#     have exited)
#
# The first render succeeds and every later one fails. So all Playwright work
# is marshalled onto one dedicated worker thread that outlives any rerun.
# max_workers=1 also serialises renders, which is why there is no lock here.
# --------------------------------------------------------------------------
_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_pw = None
_browser = None
_pages: dict[tuple, object] = {}


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="enclave-render"
            )
        return _executor


def run_in_browser_thread(fn, *args, **kwargs):
    """Run fn on the thread that owns Playwright, blocking for the result.

    Anything touching a Playwright object must go through here, including
    health checks — otherwise it creates greenlets on a thread that will exit.
    """
    return _get_executor().submit(fn, *args, **kwargs).result()


# --------------------------------------------------------------------------
# Fonts: inlined as base64 so the HTML is self-contained and path-independent
# --------------------------------------------------------------------------
def _font_face(family: str, filename: str, weight: int = 400) -> str:
    data = base64.b64encode((FONTS / filename).read_bytes()).decode()
    return (
        "@font-face{"
        f"font-family:'{family}';font-style:normal;font-weight:{weight};"
        f"src:url(data:font/ttf;base64,{data}) format('truetype');"
        "font-display:block}"
    )


_FONT_CSS: str | None = None


def font_css() -> str:
    global _FONT_CSS
    if _FONT_CSS is None:
        _FONT_CSS = "".join([
            _font_face("Anton", "Anton-Regular.ttf"),
            _font_face("Bebas Neue", "BebasNeue-Regular.ttf"),
            _font_face("Barlow Condensed", "BarlowCondensed-Medium.ttf", 500),
            _font_face("Barlow Condensed", "BarlowCondensed-Bold.ttf", 700),
        ])
    return _FONT_CSS


_GRAIN: str | None = None


def grain_tile() -> str:
    """A 128px noise tile as a data URI. Chromium tiles this almost for free,
    whereas an inline feTurbulence filter re-rasterises the whole canvas at
    device scale on every render — it was costing ~3s a card."""
    global _GRAIN
    if _GRAIN is None:
        import random
        from PIL import Image
        random.seed(7)
        n = 128
        img = Image.new("L", (n, n))
        img.putdata([random.randint(96, 160) for _ in range(n * n)])
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        _GRAIN = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return _GRAIN


def image_data_uri(path: str | pathlib.Path) -> str:
    """Turn a local jpg/png into a data URI so Chromium never touches the disk."""
    p = pathlib.Path(path)
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


# --------------------------------------------------------------------------
# Templating
# --------------------------------------------------------------------------
_env = Environment(
    loader=FileSystemLoader(ROOT / "templates"),
    autoescape=select_autoescape(["html"]),
)


def build_html(template: str, ctx: dict, size: str = "portrait") -> str:
    w, h = SIZES[size]
    payload = {
        "season": "Enclave FPL 2026/27",
        **ctx,
        "width": w,
        "height": h,
        "font_css": font_css(),
        "brand_css": (STATIC / "brand.css").read_text(),
        "grain": grain_tile(),
    }
    return _env.get_template(template).render(**payload)


# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------
def _get_browser():
    global _pw, _browser
    if _browser is None:
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage", "--font-render-hinting=none"]
        )
    return _browser


def _close_everything():
    """Must run on the browser thread — closing from elsewhere raises the same
    greenlet error it is meant to clean up after."""
    global _pw, _browser
    _pages.clear()
    if _browser:
        _browser.close()
        _browser = None
    if _pw:
        _pw.stop()
        _pw = None


def _shutdown():
    global _executor
    if _executor is None:
        return
    try:
        _executor.submit(_close_everything).result(timeout=10)
    except Exception:
        pass
    _executor.shutdown(wait=False)
    _executor = None


atexit.register(_shutdown)


def _capture(html: str, w: int, h: int, scale: int, lossless: bool) -> bytes:
    """Rasterise the page. Runs ONLY on the browser thread."""
    browser = _get_browser()
    key = (w, h, scale)
    page = _pages.get(key)
    if page is None:
        # One warm page per geometry. Reusing it keeps the decoded fonts in
        # Chromium's memory instead of re-parsing ~600KB of base64 every time.
        page = browser.new_page(
            viewport={"width": w, "height": h},
            device_scale_factor=scale,
        )
        _pages[key] = page

    try:
        page.set_content(html, wait_until="load")
        page.evaluate("() => document.fonts.ready")
        return (page.screenshot(type="png") if lossless
                else page.screenshot(type="jpeg", quality=97))
    except Exception:
        # A crashed page poisons its cache entry: every later render of this
        # geometry would fail against a dead target. Drop it so the next call
        # builds a fresh one.
        _pages.pop(key, None)
        try:
            page.close()
        except Exception:
            pass
        raise


def render(
    template: str,
    ctx: dict,
    size: str = "portrait",
    scale: int = 3,
    lossless: bool = False,
) -> bytes:
    """Render a card and return PNG bytes at the preset's nominal size.

    The intermediate capture is JPEG q=97 by default. Chromium spends ~2.8s
    PNG-encoding a 3x frame versus 0.8s for JPEG, and since the frame is
    immediately Lanczos-downsampled the difference measures 0.27/255 mean
    absolute error — invisible. Pass lossless=True for a pure PNG chain.
    """
    w, h = SIZES[size]
    html = build_html(template, ctx, size)

    raw = run_in_browser_thread(_capture, html, w, h, scale, lossless)

    # Downsample the supersampled capture — this is the quality step.
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if img.size != (w, h):
        img = img.resize((w, h), Image.LANCZOS)

    out = io.BytesIO()
    # optimize=True costs 2.5s here and saves 6% — not a trade worth making
    # in a request path.
    img.save(out, format="PNG", compress_level=6)
    out.seek(0)
    return out.getvalue()
