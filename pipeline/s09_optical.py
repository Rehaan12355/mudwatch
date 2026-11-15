"""Step 9: what an ordinary satellite camera saw.

Fetches true-colour pictures of the study window from NASA's Harmonized
Landsat Sentinel-2 (HLS) imagery, through the NASA Worldview snapshot service,
for the three weeks after ignition. The haziest one is kept: it is the
picture an optical burn map would have had to work from that day.
"""
import datetime as dt
import io
import json

import numpy as np
import requests
from PIL import Image

from common import UA, record_source
from config import SITE_DATA, WORK

SNAP = "https://wvs.earthdata.nasa.gov/api/v1/snapshot"
LAYERS = {"HLS_S30_Nadir_BRDF_Adjusted_Reflectance": "Sentinel-2", "HLS_L30_Nadir_BRDF_Adjusted_Reflectance": "Landsat"}
DAYS = 21


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    w, s, e, n = fire["bbox"]
    g = fire["grid"]
    start = dt.date.fromisoformat(fire["usgs"]["start_date"])
    views = []
    for i in range(DAYS):
        day = (start + dt.timedelta(days=i)).isoformat()
        for layer, sat in LAYERS.items():
            r = requests.get(SNAP, params={"REQUEST": "GetSnapshot", "TIME": day, "BBOX": f"{s},{w},{n},{e}", "CRS": "EPSG:4326", "LAYERS": layer,
                                           "FORMAT": "image/jpeg", "WIDTH": g["width"] * 2, "HEIGHT": g["height"] * 2}, headers=UA, timeout=180)
            if not r.ok or not r.headers.get("content-type", "").startswith("image"):
                continue
            a = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB")).astype("float32")
            seen = a.sum(2) > 30                       # black = the satellite did not image this ground that day
            if seen.mean() < 0.5:
                continue
            # Smoke and cloud are bright in every colour at once; forest and soil are not.
            haze = float((a.min(2)[seen] > 140).mean())
            views.append({"date": day, "satellite": sat, "layer": layer, "seen": round(float(seen.mean()), 2), "haze": round(haze, 2), "jpg": r.content})
            print(day, sat, f"seen {seen.mean():.0%} haze {haze:.0%}")
    if not views:
        (WORK / "optical.json").write_text(json.dumps({"ok": False}))
        return
    whole = [v for v in views if v["seen"] >= 0.95] or views      # prefer a picture of the whole window
    pick = max(whole, key=lambda v: v["haze"])
    clear = next((v["date"] for v in views if v["date"] > start.isoformat() and v["seen"] >= 0.95 and v["haze"] < 0.05), None)
    (SITE_DATA / "optical.jpg").write_bytes(pick["jpg"])
    out = {"ok": True, "date": pick["date"], "satellite": pick["satellite"], "haze_share": pick["haze"], "seen_share": pick["seen"], "bounds": [w, s, e, n], "first_clear_view": clear,
           "days_checked": DAYS, "views": [{k: v[k] for k in ("date", "satellite", "seen", "haze")} for v in views]}
    (WORK / "optical.json").write_text(json.dumps(out, indent=1))
    record_source("hls_true_colour", title=f"NASA HLS true-colour image, {pick['satellite']}, {pick['date']}",
                  url=f"{SNAP}?REQUEST=GetSnapshot&TIME={pick['date']}&BBOX={s},{w},{n},{e}&CRS=EPSG:4326&LAYERS={pick['layer']}&FORMAT=image/jpeg&WIDTH={g['width'] * 2}&HEIGHT={g['height'] * 2}",
                  licence="NASA open data (CC0); contains modified Copernicus Sentinel data, ESA", path=SITE_DATA / "optical.jpg",
                  note=f"NASA Worldview Snapshots (GIBS). The haziest of {len(views)} usable views in the {DAYS} days after ignition; {pick['haze']:.0%} of it is smoke or cloud.")
    print("kept", pick["date"], pick["satellite"])


if __name__ == "__main__":
    main()
