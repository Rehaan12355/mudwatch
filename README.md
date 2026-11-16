# Mudwatch

**NASA Space Apps Challenge 2026 · Seattle · "Dancing with the SARs"**

**Winner of the Local Impact Award at NASA Space Apps Seattle 2026.**

The headline result is the East Evans Creek Fire in Jackson County, Oregon. Radar
mapped its burn scar through the smoke eight days after it started, and Mudwatch
found 17 homes, about 43 people, sitting in a possible mud path below the steep
burned hills. It flagged the first of those homes on July 18, 116 days before the
date on the USGS expert assessment, and the two agree on 119 of 150 basins.

Live site: <https://rehaan12355.github.io/mudwatch/>

After a wildfire, the next heavy rain can bury homes in mud. Mudwatch uses radar
satellites to show which homes sit below fresh burn scars on steep slopes, fast enough
to warn people before the rain comes.

One map, three stacked layers: burn scar, slope, people. Where all three line up, the
map turns red.

## At a glance

| | East Evans Creek, OR | Bradeen Hill, WA |
|---|---|---|
| Fire started | July 10, 2026 | July 25, 2026 |
| First radar-confirmed scar | July 18 (day 8) | August 11 (day 17) |
| Radar-confirmed scar | 6,983 acres, 49 passes | 1,011 acres, 18 passes |
| Burned and 23° or steeper | 1,271 acres | 139 acres |
| Homes in a possible mud path | 17 (about 43 people) | 11 (about 28 people) |
| Lead over the USGS assessment | 116 days | 24 days |
| Basins agreeing with USGS | 119 of 150 | 42 of 54 |
| NISAR L-band HV drop over scar | 3.3 dB | 3.0 dB |

## What it found: East Evans Creek Fire, Jackson County, Oregon

The fire started on July 10, 2026. Every figure below is produced by the pipeline.

- **Radar mapped the scar through the smoke.** On July 15 an optical satellite view of
  the area was 37% smoke. Sentinel-1 radar confirmed the first scar on July 18, day 8.
  By November 11 it had confirmed 6,983 acres (28.3 km²) over 49 passes.
- **1,271 acres are burned and 23° or steeper.** These are the red zones.
- **17 homes, about 43 people, sit in a possible mud path** below those slopes, and 17
  more homes are within 100 m of one. 6.2 km of public road run through the paths,
  most of it East Evans Creek Road.
- **Every way out crosses a possible mud path.** The flagged homes leave along East
  Evans Creek Road, in either direction, or along Antioch Road, and each route runs
  through at least one path, so the advice is to leave before the rain. The map marks 17
  points where a mud channel meets a public road, for crews to clear first.
- **It agrees with the experts.** The USGS assessment of the same fire is dated
  November 11, 116 days after our first flagged home. Basin by basin, our red-zone
  share ranks the same way as the USGS terrain term (Spearman 0.71), and 119 of 150
  basins get the same answer from both. We miss 15 basins USGS rates Moderate or High
  and flag 16 it rates Low.
- **NISAR sees it too.** NISAR's L-band HV echo fell by a median of 3.3 dB over the
  Sentinel-1 scar and 0.2 dB over the rest of the window.

## What it found: Bradeen Hill Fire, Stevens County, Washington

The fire started on July 25, 2026, in forested hills above Lake Roosevelt. The result
here is weaker than in Oregon, and the site shows that as it is.

- Radar confirmed the first scar on August 11, day 17, and 1,011 acres (4.1 km²) by
  November 8 over 18 passes. That is 18% of the official perimeter, and 79% of the
  radar scar falls inside it.
- 139 acres are burned and 23° or steeper.
- **11 homes, about 28 people, sit in a possible mud path**, mostly along Daisy Mine
  Road and State Route 25. The first was flagged on August 23, 24 days before the
  USGS assessment dated September 16.
- 42 of 54 USGS basins get the same answer from both. We miss 10 of the 16 basins
  USGS rates Moderate. Our red-zone share tracks the USGS terrain term (Spearman
  0.53) but not its final likelihood (0.14).
- Smoke was not the obstacle here: an optical satellite had a clear view two days
  after ignition.
- NISAR's L-band HV echo fell by a median of 3.0 dB over the scar and 0.5 dB elsewhere.

Not every fire works. On the Three Queens Fire (Kittitas County, Washington) the burn
did not darken the Sentinel-1 picture at all, so the rule found almost nothing and
that fire is not on the site.

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
| `s06b_routes.py` | Ways out by road for every flagged home, and the points where a mud path meets a public road |
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

## Two kinds of visitor

The site asks who is using the map when it opens, and the choice can be changed in
the header.

- **Resident and first responder** both see the ways out by road: the shortest drive
  on the OpenStreetMap road network from each flagged home to a main road at least
  1 km clear of every mapped mud path. Road inside a path is drawn dashed. On both
  fires every way out runs through at least one possible mud path, which is the
  reason to leave before the rain.
- **First responder** also sees clearing points: where a mud channel crosses a
  public road, ranked by ways out first and then by the steep burned ground that
  drains to the crossing. There are 17 on East Evans Creek and 11 on Bradeen Hill.

Neither is an official product. No public evacuation-route map or debris-basin
inventory exists for these fires, and OpenStreetMap maps no basins in either
window, so both are worked out from the road map and the mud paths, and the site
says so wherever they appear.

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
