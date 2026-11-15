"""Step 2: radar pictures of the ground, pass by pass.

NASA's OPERA RTC-S1 product is Sentinel-1 radar backscatter that has already
been calibrated, terrain-corrected and placed on a 30 m map grid: a finished
product, not raw radar. It is the same input NASA's own OPERA DIST-ALERT-S1
disturbance alerts are built from.

For every Sentinel-1 pass over the study window, from BASELINE_DAYS before
ignition until today, this step reads only the window we need from each burst
file and joins the bursts of one pass into one picture per polarization.

Needs a free NASA Earthdata login in ~/.netrc (never committed).
"""
import datetime as dt
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import earthaccess
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling

from common import record_source
from config import BASELINE_DAYS, FIRE, WORK

SHORT_NAME = "OPERA_L2_RTC-S1_V1"
OUT = WORK / "rtc"
OUT.mkdir(parents=True, exist_ok=True)
NAME = re.compile(r"RTC-S1_T(\d{3})-(\d{6})-(IW\d)_(\d{8})T(\d{6})Z_(\d{8}T\d{6})Z_(S1\w)_")



def read(session, url, grid):
    """One layer of one burst, on the analysis grid. Burst files are a few MB, so each is fetched whole."""
    tf = from_origin(grid["x0"], grid["y1"], grid["res"], grid["res"])
    for attempt in range(4):
        try:
            r = session.get(url, timeout=180)
            r.raise_for_status()
            break
        except Exception:
            if attempt == 3:
                raise
    with MemoryFile(r.content) as mem, mem.open() as src, WarpedVRT(
        src, crs=f"EPSG:{grid['epsg']}", transform=tf, width=grid["width"], height=grid["height"], resampling=Resampling.nearest
    ) as vrt:
        return vrt.read(1, masked=True)


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    grid = fire["grid"]
    start = dt.date.fromisoformat(fire["usgs"]["start_date"])
    earthaccess.login(strategy="netrc")
    session = earthaccess.get_requests_https_session()
    res = earthaccess.search_data(short_name=SHORT_NAME, bounding_box=tuple(fire["bbox"]),
                                  temporal=(str(start - dt.timedelta(days=BASELINE_DAYS)), str(dt.date.today())), count=5000)
    # One file set per burst and acquisition: keep the most recently produced copy.
    latest = {}
    for g in res:
        links = g.data_links()
        m = NAME.search(links[0])
        key = (m.group(1), m.group(2), m.group(3), m.group(4))
        if key not in latest or m.group(6) > latest[key][0]:
            latest[key] = (m.group(6), m.group(5), m.group(7), links)
    passes = defaultdict(list)   # (date, track) -> bursts
    for (track, burst, iw, date), (_, hhmmss, sat, links) in latest.items():
        passes[(date, track)].append((burst, iw, hhmmss, sat, links))
    print(len(res), "burst files,", len(latest), "unique,", len(passes), "passes on tracks", sorted({t for _, t in passes}))

    def build(item):
        (date, track), bursts = item
        out = OUT / f"{date}_T{track}.npz"
        if out.exists():
            return out, 0
        layers = {pol: np.full((grid["height"], grid["width"]), np.nan, "float32") for pol in ("VH", "VV")}
        for burst, iw, hhmmss, sat, links in sorted(bursts):
            # The layover/shadow mask: 0 is a clean look at the ground.
            mk = read(session, next(l for l in links if l.endswith("_mask.tif")), grid)
            for pol in ("VH", "VV"):
                a = read(session, next(l for l in links if l.endswith(f"_{pol}.tif")), grid)
                ok = ~np.ma.getmaskarray(a) & np.isfinite(a.filled(np.nan)) & (a.filled(0) > 0) & (mk.filled(255) == 0)
                layers[pol] = np.where(np.isnan(layers[pol]) & ok, a.filled(np.nan), layers[pol])
        b0 = sorted(bursts)[0]
        np.savez_compressed(out, VH=layers["VH"], VV=layers["VV"], date=date, track=track, time=b0[2], sat=b0[3],
                            granules=json.dumps([l[4][0].rsplit("/", 1)[-1].replace("_VH.tif", "").replace(".h5", "") for l in sorted(bursts)]))
        return out, 1

    with ThreadPoolExecutor(6) as ex:
        done = list(ex.map(build, sorted(passes.items())))
    rows = []
    for path, _ in done:
        z = np.load(path)
        rows.append({"date": str(z["date"]), "track": str(z["track"]), "time_utc": str(z["time"]), "satellite": str(z["sat"]),
                     "coverage": round(float(np.isfinite(z["VH"]).mean()), 3), "granules": json.loads(str(z["granules"]))})
    rows.sort(key=lambda r: (r["date"], r["time_utc"]))
    (WORK / "passes.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        print(r["date"], "T" + r["track"], r["time_utc"], r["satellite"], f"{r['coverage']:.0%}", len(r["granules"]), "bursts")
    record_source(
        "opera_rtc_s1",
        title=f"NASA OPERA L2 RTC-S1 v1 radar backscatter, {len(rows)} Sentinel-1 passes {rows[0]['date']} to {rows[-1]['date']}, study-window subset",
        url="https://search.asf.alaska.edu/#/?dataset=OPERA-S1&productTypes=RTC",
        licence="NASA open data (CC0); contains modified Copernicus Sentinel-1 data, ESA",
        path=None,
        note=f"Short name {SHORT_NAME} at the Alaska Satellite Facility DAAC (Earthdata login). "
             f"VH, VV and mask layers of {len(latest)} burst files on tracks {', '.join(sorted({r['track'] for r in rows}))}; only the study window was read "
             f"({sum(p.stat().st_size for p, _ in done) / 1e6:.0f} MB kept in data/work/{FIRE['id']}/rtc/).",
    )


if __name__ == "__main__":
    main()
