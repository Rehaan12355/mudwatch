# Mudslide Watch

**NASA Space Apps Challenge 2026 · Seattle · "Dancing with the SARs"**

After a wildfire, the next heavy rain can bury homes in mud. Mudslide Watch uses radar
satellites to show which homes sit below fresh burn scars on steep slopes, fast enough
to warn people before the rain comes.

One map, three stacked layers: burn scar, slope, people. Where all three line up, the
map turns red.

## What it found: East Evans Creek Fire, Jackson County, Oregon

The fire started on July 10, 2026. Every figure below is produced by the pipeline.

- **Radar mapped the scar through the smoke.** On July 15 an optical satellite view of
  the area was 37% smoke. Sentinel-1 radar confirmed the first scar on July 18, day 8.
  By November 11 it had confirmed 6,983 acres (28.3 km²) over 49 passes.
- **1,271 acres are burned and 23° or steeper.** These are the red zones.
- **17 homes, about 43 people, sit in a possible mud path** below those slopes, and 17
  more homes are within 100 m of one. 6.2 km of public road run through the paths,
  most of it East Evans Creek Road.
- **It agrees with the experts.** The USGS assessment of the same fire is dated
  November 11, 116 days after our first flagged home. Basin by basin, our red-zone
  share ranks the same way as the USGS terrain term (Spearman 0.71), and 119 of 150
  basins get the same answer from both. We miss 15 basins USGS rates Moderate or High
  and flag 16 it rates Low.
- **NISAR sees it too.** NISAR's L-band HV echo fell by a median of 3.3 dB over the
  Sentinel-1 scar and 0.2 dB over the rest of the window.

## One change from the plan

The handout names NASA OPERA **DIST-ALERT-S1** as the main burn-scar source. Its archive
currently holds January and February 2026 only, anywhere in the world, so it does not
reach any 2026 fire season yet (`pipeline/s02b_dist.py` checks and records this).

The scar is therefore drawn from **OPERA RTC-S1**, the calibrated, terrain-corrected
Sentinel-1 backscatter that DIST-ALERT-S1 is itself made from, with the same
confirm-over-several-passes idea. It is still a finished NASA radar product, and it is
what gives the slider a real pass-by-pass history. The handout's other fallback, the
USGS perimeter, is used as ground truth instead of as the scar.

## How it is put together

- `pipeline/`: Python steps that download public data and precompute everything.
- `site/`: a static website (no server, no login) that reads `site/data/`.
- `DESIGN.md`: the design system the site follows.
- `DATA_SOURCES.md`: every dataset's URL, retrieval date, size and licence.

The app structure, slider, summary cards and deploy workflow are carried over from
Sinking Cities; the data layers are new.

| Step | What it does |
|---|---|
| `s01_fire.py` | Finds the fire in the USGS debris-flow hazard collection; downloads perimeter, basins, segments; sets the 30 m grid |
| `s02_radar.py` | Reads OPERA RTC-S1 backscatter for every Sentinel-1 pass from 60 days before ignition to today |
| `s02b_dist.py` | Checks whether OPERA DIST-ALERT-S1 covers the fire yet |
| `s03_scar.py` | Burn scar: ground that went 1.25 dB darker for 3 passes in a row; scored against the perimeter |
| `s04_slope.py` | NASADEM elevation and slope |
| `s05_people.py` | 2020 Census blocks, USA Structures buildings, OpenStreetMap names and roads |
| `s06_zones.py` | Red zones (burned and steep), the paths below them, homes and people in the way, for every pass |
| `s07_usgs.py` | Basin-by-basin comparison with the USGS assessment |
| `s08_nisar.py` | NISAR GCOV L-band backscatter before and after |
| `s09_optical.py` | The haziest NASA HLS true-colour view in the three weeks after ignition |
| `s10_build.py` | Packages everything for the website |

## Run it

```
python3.13 -m venv .venv && .venv/bin/pip install earthaccess geopandas rasterio h5py scipy pillow requests certifi
MW_FIRE=east-evans-creek sh pipeline/run_all.sh
cd site && python -m http.server 8000
```

Steps 2, 2b, 4 and 8 need a free NASA Earthdata login stored in `~/.netrc`.
Credentials are never stored in this repository. A full build transfers roughly 1 GB
and takes about ten minutes.

To add a fire, add an entry to `FIRES` in `pipeline/config.py` with the name USGS
uses for it, then run the pipeline with `MW_FIRE=<id>`. The site's picker lists every
fire that has been built.

## The 30-second demo

Press **Play the story**. It runs the handout's sequence with real data:

1. July 15, optical view: smoke.
2. Sentinel-1 radar, July 14: the ground.
3. The burn scar grows pass by pass.
4. Slope switches on and steep burned hills turn red.
5. People switches on and the homes below light up, with a count.
6. The USGS map, side by side.

## Limits

This is a screen, not a debris-flow model. It flags risk zones; it does not predict
mudslides. It says "could", never "will". Burned and steep is a rough rule that knows
nothing about rainfall, soil or sediment supply, the radar misses light burns under
intact canopy, and paths are drawn narrow. The USGS model is the expert version. The
full list is on the site's "How it works" page.

## AI disclosure

This project was built with help from Claude (Anthropic) for code and text drafting.
All data comes from the public sources listed in `DATA_SOURCES.md`; no values are
AI-generated.
