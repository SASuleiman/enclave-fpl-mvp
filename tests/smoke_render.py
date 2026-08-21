"""
Deployment smoke test.

Proves the rendering pipeline works on a clean Ubuntu box with only
packages.txt + requirements.txt installed — the same starting conditions as
Streamlit Cloud. Uses synthetic data so it never depends on the FPL API being
up, and imports nothing from Streamlit.

Exits non-zero with a readable reason on failure, so CI is a real gate.
"""

import io
import pathlib
import resource
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402
from PIL import Image  # noqa: E402

from enclave_fpl.graphics import CATALOGUE, SIZES, render  # noqa: E402

OUT = pathlib.Path("smoke-output")

ROWS = [
    {"Rank": 1, "Previous Rank": 3, "Manager": "Ade", "Team": "Ade FC",
     "GW Points": 58, "Total Points": 764, "Rank Movement": 2, "Gap to Leader": 0},
    {"Rank": 2, "Previous Rank": 1, "Manager": "Kunle", "Team": "Kunle City",
     "GW Points": 46, "Total Points": 742, "Rank Movement": -1, "Gap to Leader": 22},
    {"Rank": 3, "Previous Rank": 17, "Manager": "Tunde", "Team": "Tunde's Titans",
     "GW Points": 61, "Total Points": 731, "Rank Movement": 14, "Gap to Leader": 33},
    {"Rank": 4, "Previous Rank": 4, "Manager": "Femi", "Team": "Femi XI",
     "GW Points": 12, "Total Points": 715, "Rank Movement": 0, "Gap to Leader": 49},
]


def main() -> int:
    OUT.mkdir(exist_ok=True)
    df = pd.DataFrame(ROWS)
    failures = []

    print(f"python {sys.version.split()[0]}")
    try:
        from enclave_fpl.browser import ensure_chromium
        print(f"chromium {ensure_chromium()}")
    except Exception as e:
        print(f"FATAL: {e}")
        return 1

    for name, fn in CATALOGUE.items():
        template, ctx = fn(df, 12)
        try:
            start = time.perf_counter()
            png = render(template, ctx, size="portrait", scale=3)
            elapsed = time.perf_counter() - start

            img = Image.open(io.BytesIO(png))
            assert img.size == SIZES["portrait"], f"wrong size {img.size}"
            # A blank or all-black card still decodes fine, so check the render
            # actually put ink down — this catches silent font/CSS failures.
            colours = len(img.convert("RGB").getcolors(maxcolors=1_000_000) or [])
            assert colours > 500, f"only {colours} distinct colours — card looks blank"

            (OUT / f"{template.replace('.html', '')}.png").write_bytes(png)
            print(f"  PASS  {name:24s} {elapsed:5.2f}s  {len(png) / 1024:5.0f}KB  {colours} colours")
        except Exception as e:
            failures.append(f"{name}: {type(e).__name__}: {e}")
            print(f"  FAIL  {name:24s} {e}")

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"\npeak python RSS: {peak_mb:.0f} MB (Chromium is a separate process)")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(" -", f)
        return 1
    print(f"\nAll {len(CATALOGUE)} cards rendered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
