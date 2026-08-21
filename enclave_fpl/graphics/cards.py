"""
Maps the league dataframe from the Streamlit app into card contexts.

Every function returns (template_name, context). Keep the FPL logic here and
the visual decisions in templates/ — that way a design change never touches
the API code, and vice versa.
"""

from __future__ import annotations

import math

import pandas as pd

SEASON = "Enclave FPL 2026/27"


def _ordinal(n) -> str:
    n = int(n)
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _safe(v, default=0):
    return default if v is None or (isinstance(v, float) and math.isnan(v)) else v


def table_card(df: pd.DataFrame, gw: int, top: int = 8, photo: str | None = None):
    rows = (
        df.sort_values("Rank")
        .head(top)
        .apply(
            lambda r: dict(
                pos=int(_safe(r["Rank"], 0)),
                name=str(r["Manager"]).upper(),
                total=int(_safe(r["Total Points"])),
                gw=int(_safe(r["GW Points"])),
            ),
            axis=1,
        )
        .tolist()
    )
    return "table.html", dict(gw=gw, rows=rows, photo=photo, season=SEASON)


def climber_card(df: pd.DataFrame, gw: int, photo: str | None = None):
    r = df.sort_values("Rank Movement", ascending=False).iloc[0]
    moved = int(_safe(r["Rank Movement"]))
    return "climber.html", dict(
        gw=gw,
        name=str(r["Manager"]).upper(),
        places=moved,
        from_rank=_ordinal(_safe(r["Previous Rank"], r["Rank"])),
        to_rank=_ordinal(_safe(r["Rank"])),
        points=int(_safe(r["GW Points"])),
        watermark=moved,
        photo=photo,
        season=SEASON,
    )


def motw_card(df: pd.DataFrame, gw: int, photo: str | None = None):
    r = df.sort_values("GW Points", ascending=False).iloc[0]
    moved = int(_safe(r["Rank Movement"]))
    pts = int(_safe(r["GW Points"]))
    return "motw.html", dict(
        gw=gw,
        name=str(r["Manager"]).upper(),
        team=str(r["Team"]),
        points=pts,
        movement=f"{moved:+d} positions" if moved else "Held the top",
        watermark=pts,
        photo=photo,
        season=SEASON,
    )


def damage_card(df: pd.DataFrame, gw: int, notes: list[str] | None = None,
                photo: str | None = None):
    r = df.sort_values("GW Points").iloc[0]
    moved = int(_safe(r["Rank Movement"]))
    pts = int(_safe(r["GW Points"]))
    auto = [f"Lowest score in the league", f"{moved:+d} positions"]
    return "damage.html", dict(
        gw=gw,
        name=str(r["Manager"]).upper(),
        points=pts,
        notes=[n.upper() for n in (notes or auto)],
        verdict="A rough week.",
        watermark=pts,
        photo=photo,
        season=SEASON,
    )


def review_card(df: pd.DataFrame, gw: int, photo: str | None = None):
    best = df.sort_values("GW Points", ascending=False).iloc[0]
    worst = df.sort_values("GW Points").iloc[0]
    leader = df.sort_values("Total Points", ascending=False).iloc[0]
    return "review.html", dict(
        gw=gw,
        ledger=[
            ("The good", f'{best["Manager"]} — {int(_safe(best["GW Points"]))} pts'),
            ("The bad", f'{worst["Manager"]} — {int(_safe(worst["GW Points"]))} pts'),
            ("Top of the pile", f'{leader["Manager"]} — {int(_safe(leader["Total Points"])):,}'),
        ],
        photo=photo,
        season=SEASON,
    )


def deadline_card(gw: int, countdown: str, deadline_local: str, photo: str | None = None):
    return "deadline.html", dict(
        gw=gw, countdown=countdown, deadline_local=deadline_local.upper(),
        photo=photo, season=SEASON,
    )


CATALOGUE = {
    "The table": table_card,
    "Biggest climber": climber_card,
    "Manager of the week": motw_card,
    "Damage report": damage_card,
    "Gameweek review": review_card,
}
