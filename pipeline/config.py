"""Fire configuration. Add a fire to FIRES and run the pipeline with
MW_FIRE=<id> to build it; the website lists every fire that has been built."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FIRES = {
    "east-evans-creek": {
        "name": "East Evans Creek Fire, Oregon",
        "short_name": "East Evans Creek",
        # Name of the fire in the USGS post-wildfire debris-flow hazard collection.
        "usgs_fire": "East Evans Creek",
        "state": "Oregon",
        "county": "Jackson County",
        "state_fips": "41",
        "counties": {"029": "Jackson County"},
        "utm_epsg": 32610,
        # National Weather Service office that issues flash flood warnings here.
        "nws_office": "Medford",
        "nws_url": "https://www.weather.gov/mfr/",
        "why": "The East Evans Creek Fire burned steep, forested ridges above the homes strung along East Evans Creek and its side "
               "valleys north of Wimer and the town of Rogue River. It sits west of the Cascades, where the autumn rains arrive weeks after the fire season ends.",
    },
    "bradeen-hill": {
        "name": "Bradeen Hill Fire, Washington",
        "short_name": "Bradeen Hill",
        "usgs_fire": "Bradeen Hill",
        "state": "Washington",
        "county": "Stevens County",
        "state_fips": "53",
        "counties": {"065": "Stevens County"},
        "utm_epsg": 32611,
        "nws_office": "Spokane",
        "nws_url": "https://www.weather.gov/otx/",
        "why": "The Bradeen Hill Fire burned forested hills above Lake Roosevelt between Daisy and Gifford in Stevens County. "
               "Homes sit along Daisy Mine Road and State Route 25 at the foot of those hills.",
    },
}

FIRE_ID = os.environ.get("MW_FIRE", "east-evans-creek")
FIRE = dict(FIRES[FIRE_ID], id=FIRE_ID)
# common.py was written for cities; it only needs an id and a short name.
CITY = FIRE

RAW = ROOT / "data" / "raw" / FIRE_ID          # downloads, not committed
WORK = ROOT / "data" / "work" / FIRE_ID        # intermediate products, not committed
SITE_DATA = ROOT / "site" / "data" / FIRE_ID   # what the website loads, committed
for _d in (RAW, WORK, SITE_DATA):
    _d.mkdir(parents=True, exist_ok=True)

GRID_M = 30            # analysis grid, metres: the native grid of the OPERA radar products
PAD_M = 4000           # how far the study window reaches beyond the burn perimeter
BASELINE_DAYS = 60     # radar passes this many days before ignition set each track's "before" picture

# The screen itself: burned AND steep.
# 23 degrees is the gradient the USGS likelihood model (Staley and others, 2017) uses for its terrain term.
STEEP_DEG = 23.0
# How far below a flagged slope the mud path is drawn. See s06_zones.py.
RUNOUT_STOP_DEG = 3.0   # a channel flatter than this for RUNOUT_FLAT_M is where the path ends
RUNOUT_FLAT_M = 300
RUNOUT_MAX_M = 3000     # never drawn further than this below the last flagged slope
PATH_HALF_WIDTH_M = 45  # the path is drawn this wide either side of the channel
MIN_SOURCE_HA = 1.0     # flagged slope needed above a point before a path is drawn from it
NEAR_PATH_M = 100       # homes this close to a path are listed as "next to" it
