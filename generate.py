"""
Render the weekly card set from the command line — no Streamlit involved.

    python generate.py --league 1138273 --gw 12 --out ./cards

Useful for a GitHub Action or a cron job that posts to the group chat
automatically after each gameweek settles.
"""

import argparse
import pathlib

from enclave_fpl import fpl
from enclave_fpl.graphics import CATALOGUE, image_data_uri, render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", type=int, default=fpl.DEFAULT_LEAGUE_ID)
    ap.add_argument("--gw", type=int, default=None, help="defaults to the current gameweek")
    ap.add_argument("--out", type=pathlib.Path, default=pathlib.Path("cards"))
    ap.add_argument("--size", default="portrait")
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--photo", type=pathlib.Path, default=None)
    args = ap.parse_args()

    _, rows, _ = fpl.all_managers(args.league)
    df = fpl.manager_df(rows)
    if df.empty:
        raise SystemExit("No managers returned for that league.")

    gw = args.gw or fpl.current_gw()
    photo = image_data_uri(args.photo) if args.photo else None

    args.out.mkdir(parents=True, exist_ok=True)
    for name, fn in CATALOGUE.items():
        template, ctx = fn(df, gw, photo=photo)
        path = args.out / f"gw{gw}_{name.lower().replace(' ', '_')}.png"
        path.write_bytes(render(template, ctx, size=args.size, scale=args.scale))
        print("wrote", path)


if __name__ == "__main__":
    main()
