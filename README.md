# Enclave FPL Intelligence

Analytics and matchday graphics for the Bar Enclave private Classic League.
Pulls live data from the Fantasy Premier League API and renders the weekly
card set — table, biggest climber, manager of the week, damage report, review —
in the Enclave brand at 1080×1350 and up.

## Quick start

```bash
git clone <your-repo-url> && cd enclave-fpl
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

Set your league in the sidebar, or change `DEFAULT_LEAGUE_ID` in
`enclave_fpl/fpl.py`.

To render the whole set without opening the app:

```bash
python generate.py --gw 12 --out ./cards
python generate.py --photo static/photos/roar.jpg --size story
```

## Layout

```
app.py                        Streamlit entrypoint
generate.py                   CLI renderer — cron / GitHub Actions
enclave_fpl/
  fpl.py                      FPL API client and dataframes
  ui.py                       Streamlit graphics section
  graphics/
    render.py                 HTML → Chromium → PNG pipeline
    cards.py                  dataframe → card context
    templates/                one Jinja template per card
    static/brand.css          every design token lives here
    static/fonts/             Anton, Bebas Neue, Barlow Condensed (OFL)
    static/photos/            drop background imagery here
requirements.txt
packages.txt                  system libs for Streamlit Cloud
```

The split matters: `fpl.py` never imports the renderer and `graphics/` never
imports Streamlit, so you can drive the cards from a script, a bot, or a
scheduled job without dragging the UI along.

## How the graphics work

Design in CSS, rasterise in headless Chromium, downsample with Lanczos.

The previous approach used Pillow's `ImageDraw`, which is why it plateaued at
coloured rectangles. Pillow has no gradients, no blend modes, no clipping
paths, and no letter-spacing control — most of the brand board is inexpressible
in it. CSS has all of those, so every texture here is generated rather than
shipped: the torn brush slashes are `clip-path` polygons, the orange duotone is
`mix-blend-mode: color-dodge` over a desaturated photo, the halftone fade is a
masked `radial-gradient`, and the grain is a 128px noise tile.

Three implementation details carry the quality:

**Supersampling.** Chromium renders at `device_scale_factor=3`, so a 1080×1350
card is captured at 3240×4050 and downsampled. That's what makes Anton's thin
counters and the tracked-out micro-labels look printed rather than
screenshotted. Rendering at 1× is the single biggest quality mistake available.

**Encoding.** The intermediate capture is JPEG q=97, not PNG. Chromium spends
~2.8s PNG-encoding a 3× frame versus ~0.8s for JPEG, and since the frame is
immediately downsampled the measured difference is 0.27/255 mean absolute error
— invisible. The final PNG uses `compress_level=6` rather than `optimize=True`,
which costs 2.5s to save 6% of file size. Pass `lossless=True` for the pure PNG
chain.

**Warm pages.** One Chromium page is cached per geometry, so decoded fonts stay
resident instead of re-parsing ~600KB of base64 on every render.

Together: 5.8s → **~1.1s per card**.

## Background photos

The photo-less cards look deliberate, but the board gets most of its heat from
imagery. Drop shots into `enclave_fpl/graphics/static/photos/` and pass one in:

```python
from enclave_fpl.graphics import image_data_uri, render, CATALOGUE
template, ctx = CATALOGUE["Biggest climber"](df, gw=12,
                                             photo=image_data_uri("…/roar.jpg"))
```

The card handles the treatment, so any photo comes out on-brand. Use licensed
stock (Unsplash, Pexels) rather than Premier League press images — FPL is
relaxed about the API, not about club photography.

## Adding a card

1. New template in `graphics/templates/` extending `_base.html`, filling the
   `body` block.
2. New function in `graphics/cards.py` returning `(template_name, context)`.
3. Add it to `CATALOGUE`.

It appears in the Streamlit picker and the CLI batch automatically. Change
`--orange` in `brand.css` and the entire set follows.

## Troubleshooting

**"The graphics engine isn't available on this host."** The app now shows the
real Playwright error in an expander instead of crashing. Match it below.

| Message contains | Cause | Fix |
|---|---|---|
| `Executable doesn't exist` | Browser binary never downloaded | Check outbound access to Playwright's CDN; hit **Retry setup** |
| `error while loading shared libraries` | Missing apt package | Add the named `.so`'s package to `packages.txt`, redeploy |
| `Target closed` / `killed` | Out of memory | Set quality to 2, or move to a bigger host |
| `Sync API inside the asyncio loop` | Threading conflict | Render in a worker thread or use the async API |

Two things that bit this project and are worth knowing:

- **Never use `playwright install --with-deps` on a managed host.** It shells out
  to `apt-get`, which has no root, and the installer exits code 100 *before
  downloading the browser*. Use plain `playwright install chromium` and let
  `packages.txt` supply the system libraries.
- **`libasound2` is a virtual package on Ubuntu 24.04** (Streamlit Cloud's base)
  with no installation candidate. apt fails on it, and the host then abandons
  the whole `packages.txt`, so you silently get *no* system libraries. Use the
  `t64` names: `libasound2t64`, `libatk1.0-0t64`, `libatk-bridge2.0-0t64`,
  `libcups2t64`.

## Deploying to Streamlit Community Cloud

Push the repo, point Streamlit Cloud at `app.py`. `packages.txt` carries the
Chromium system libraries; `ensure_chromium()` installs the browser binary on
first boot and caches with `@st.cache_resource`, so it runs once per container.

Chromium wants roughly 400MB while rendering. That fits the free tier. If you
outgrow it, move rendering to a small worker (Fly.io, Railway) and have
Streamlit call it — `render()` is already the entire API surface.

One caveat: `sync_playwright` and Streamlit's threading don't always agree. The
module-level lock in `render.py` serialises renders, which is correct for a
league tool. For real concurrency, switch to the async API with one browser per
event loop.

## CI

`.github/workflows/render-check.yml` runs on every push and PR. It installs
`packages.txt` through apt on `ubuntu-24.04` — the same base image Streamlit
Community Cloud uses — then installs Chromium and renders every card, failing
the build if any comes back blank.

This exists because two bugs reached production with nothing to catch them:
`playwright install --with-deps` aborting silently without root, and
`libasound2` being an uninstallable virtual package on 24.04, which made the
host discard the entire `packages.txt`. Both would now fail CI in about ninety
seconds.

Run it locally the same way:

```bash
python tests/smoke_render.py
```

Rendered cards upload as a build artifact, so you can eyeball the real output
on any commit without deploying.

Note the runner is pinned to `ubuntu-24.04`, not `ubuntu-latest`. When
`ubuntu-latest` rolls forward it stops matching your host, and the package-name
check quietly becomes worthless.

## Automating the weekly post

`generate.py` is designed for this. A scheduled GitHub Action that runs it after
each gameweek settles and uploads the PNGs as artifacts is about fifteen lines
of YAML, and from there a webhook can drop them straight into the group chat.

## Notes on the rewrite

Beyond the graphics, two things changed in the data layer:

- **`current_gw()` is new.** The original app never resolved which gameweek it
  was in, so every graphic would have needed a manual label. It reads
  `is_current` from `bootstrap-static`, falling back to `is_next`, then to the
  last finished gameweek in preseason.
- **`last_rank == 0` is now handled.** The API returns 0 for anyone unranked the
  previous week. Subtracting that from their current rank reported newcomers as
  climbing several hundred places, which would have put the wrong name on the
  Biggest Climber card. They now register as no movement.

## Licence and attribution

Fonts are SIL Open Font License, safe to redistribute. This is an independent
analytics tool and is not affiliated with the Premier League.
