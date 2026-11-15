"""Step 1: the fire, as the experts mapped it.

Looks the fire up in the USGS post-wildfire debris-flow hazard collection and
downloads its assessment: the burn perimeter, the drainage basins and stream
segments with their modelled debris-flow likelihood, volume and combined hazard.

This is our ground truth. It is used three ways: the perimeter checks the
radar burn scar, the basins check our red zones, and if the radar step fails
the perimeter stands in as the scar layer so the site keeps working.

Also fixes the study window and the 30 m analysis grid shared by every later step.
"""
import datetime as dt
import io
import json
import zipfile

import geopandas as gpd
import numpy as np
import requests

from common import UA, fetch, record_source
from config import FIRE, GRID_M, PAD_M, RAW, WORK

SVC = "https://earthquake.usgs.gov/arcgis/rest/services/ls/pwfdf/MapServer"


def day(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).date().isoformat()


def main():
    r = requests.get(f"{SVC}/0/query", params={"where": f"fire='{FIRE['usgs_fire']}'", "outFields": "*", "f": "json"}, headers=UA, timeout=120)
    r.raise_for_status()
    rows = [f["attributes"] for f in r.json()["features"]]
    if not rows:
        raise SystemExit(f"USGS has no assessment named {FIRE['usgs_fire']!r}")
    a = max(rows, key=lambda x: x["assessment_date"])   # the latest version
    url = a["download_url"].strip()
    z = fetch(url, "usgs_pwfdf.zip", timeout=300)
    with zipfile.ZipFile(io.BytesIO(z.read_bytes())) as zf:
        zf.extractall(RAW / "usgs")

    perim = gpd.read_file(RAW / "usgs" / "perimeter.shp").to_crs(FIRE["utm_epsg"])
    basins = gpd.read_file(RAW / "usgs" / "basins.shp")
    segments = gpd.read_file(RAW / "usgs" / "segments.shp")
    gpd.GeoDataFrame(geometry=[perim.union_all()], crs=perim.crs).to_file(WORK / "perimeter.gpkg", driver="GPKG")

    # Study window: the perimeter plus PAD_M, snapped to the 30 m grid the OPERA products use.
    x0, y0, x1, y1 = perim.total_bounds
    x0 = float(np.floor((x0 - PAD_M) / GRID_M) * GRID_M)
    y1 = float(np.ceil((y1 + PAD_M) / GRID_M) * GRID_M)
    w = int(np.ceil((x1 + PAD_M - x0) / GRID_M))
    h = int(np.ceil((y1 - (y0 - PAD_M)) / GRID_M))
    ll = gpd.GeoSeries.from_xy([x0, x0 + w * GRID_M], [y1 - h * GRID_M, y1], crs=FIRE["utm_epsg"]).to_crs(4326)
    meta = {
        "usgs": {
            "fire": a["fire"], "fire_id": a["Fire_ID"], "location": a["location"], "status": a["status"],
            "start_date": day(a["start_date"]), "assessment_date": day(a["assessment_date"]),
            "size_km2": a["size"], "design_storm": a["Rainfall"],
            "sciencebase_url": a["ScienceBaseURL"].strip(), "download_url": url,
            "n_basins": len(basins), "n_segments": len(segments),
        },
        "perimeter_km2": round(float(perim.union_all().area / 1e6), 2),
        "grid": {"epsg": FIRE["utm_epsg"], "x0": x0, "y1": y1, "width": w, "height": h, "res": GRID_M},
        "bbox": [round(float(v), 5) for v in (ll.x[0], ll.y[0], ll.x[1], ll.y[1])],
    }
    (WORK / "fire.json").write_text(json.dumps(meta, indent=1))
    record_source(
        "usgs_pwfdf",
        title=f"USGS post-wildfire debris-flow hazard assessment, {a['Fire_ID']}",
        url=a["ScienceBaseURL"].strip(),
        licence="US Government work, public domain",
        path=z,
        note=f"Looked up by fire name in {SVC} (layer 0). Assessment dated {meta['usgs']['assessment_date']}; fire start {meta['usgs']['start_date']}. "
             f"Shapefiles: perimeter, {len(basins)} basins, {len(segments)} stream segments. Part of the PWFDF collection, doi:10.5066/P14EWYME.",
    )
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
