"""
Chromium bootstrap.

Managed hosts (Streamlit Community Cloud, most PaaS) install the `playwright`
pip package from requirements.txt but not the browser binary, and give you no
root. This module downloads the binary at runtime and — critically — proves it
launches before reporting success.

The previous version ran `playwright install chromium --with-deps`. That flag
shells out to `apt-get`, which fails without root, and the installer aborts
with exit code 100 *before downloading anything*. Combined with `check=False`
and a cached `True` return, the app reported a healthy engine that had never
been installed. System libraries come from packages.txt instead, which is the
mechanism managed hosts actually provide.
"""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
import sys

logger = logging.getLogger("enclave.browser")

# Pin an explicit, writable location. Playwright's default (~/.cache) is fine
# on most hosts but is wiped on some, and being explicit makes failures legible.
DEFAULT_BROWSERS_PATH = pathlib.Path(
    os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    or (pathlib.Path.home() / ".cache" / "ms-playwright")
)


class BrowserUnavailable(RuntimeError):
    """Chromium could not be installed or launched. Carries the real reason."""


def _probe() -> str:
    """Start Chromium and report its version. Runs on the browser thread."""
    from .graphics.render import _get_browser

    return _get_browser().version


def _launch_probe() -> tuple[bool, str]:
    """Try to actually start Chromium. The only honest health check.

    Delegated to the renderer's dedicated thread rather than run inline. The
    sync Playwright API pins greenlets to whichever thread creates them, and
    Streamlit's rerun threads exit between script runs — probing from one
    would leave a second, orphaned driver behind and risk the same
    "cannot switch to a different thread" failure the renderer avoids.
    """
    try:
        from .graphics.render import run_in_browser_thread

        return True, run_in_browser_thread(_probe)
    except Exception as e:  # noqa: BLE001 — we want the message, whatever it is
        return False, f"{type(e).__name__}: {e}"


def install_chromium(timeout: int = 600) -> tuple[bool, str]:
    """Download the browser binary. No --with-deps: it needs root and aborts."""
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(DEFAULT_BROWSERS_PATH))
    DEFAULT_BROWSERS_PATH.mkdir(parents=True, exist_ok=True)

    logger.info("Installing Chromium into %s", DEFAULT_BROWSERS_PATH)
    proc = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        logger.error("playwright install failed (%s): %s", proc.returncode, output[-2000:])
    return proc.returncode == 0, output[-2000:]


def ensure_chromium() -> str:
    """Return the Chromium version, or raise BrowserUnavailable with the reason.

    Never returns a bare success flag — the old code did, and a cached lie is
    worse than a loud failure.
    """
    ok, detail = _launch_probe()
    if ok:
        return detail

    logger.info("Chromium not ready (%s) — installing", detail)
    installed, install_log = install_chromium()

    ok, detail = _launch_probe()
    if ok:
        return detail

    raise BrowserUnavailable(
        _diagnose(detail, install_log if not installed else "")
    )


def _diagnose(launch_error: str, install_log: str = "") -> str:
    """Turn Playwright's error into something you can act on."""
    e = launch_error.lower()

    if "executable doesn't exist" in e or "please run the following command" in e:
        hint = (
            "The Chromium binary is missing and the runtime download did not "
            "succeed. On a managed host this usually means no outbound access "
            "to Playwright's CDN, or no writable cache directory."
        )
    elif "error while loading shared libraries" in e or "cannot open shared object" in e:
        missing = launch_error.split("shared libraries:")[-1].split(":")[0].strip()
        hint = (
            f"A system library is missing ({missing or 'see above'}). Add it to "
            "packages.txt and redeploy — that file is how managed hosts install "
            "apt packages for you."
        )
    elif "sync api inside the asyncio loop" in e:
        hint = (
            "The sync Playwright API cannot run inside a live asyncio loop. "
            "Render in a worker thread, or switch to the async API."
        )
    elif "out of memory" in e or "killed" in e or "target closed" in e:
        hint = (
            "Chromium was killed, almost certainly by the memory limit. Drop the "
            "quality slider to 2, or render on a host with more RAM."
        )
    elif "timeout" in e:
        hint = "Chromium did not start within the timeout — usually a memory-starved host."
    else:
        hint = "See the message above for the underlying cause."

    parts = [f"Chromium could not start.\n\n{hint}\n\nPlaywright said:\n{launch_error}"]
    if install_log:
        parts.append(f"\nInstaller output:\n{install_log}")
    parts.append(
        "\nYou can always render locally instead:\n"
        "    python -m playwright install chromium\n"
        "    python generate.py --gw <n> --out ./cards"
    )
    return "\n".join(parts)
