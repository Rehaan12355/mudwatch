"""Step 7: check the screen against the experts.

The USGS assessment for the same fire models every drainage basin with
measured burn severity, soil properties and a design rainstorm. Ours uses
radar and slope only. This step asks how far the two agree, basin by basin:

- Does the radar see the burn the way the optical burn-severity map does?
  (radar darkening against the USGS fire term, mean dNBR / 1000)
- Do our red zones match the USGS terrain term, which is the same idea built
  from optical data: the share of a basin burned at moderate or high severity
  on slopes of 23 degrees or more?
- Do the basins we flag line up with the ones USGS rates Moderate or High?

Nothing here is tuned to make the numbers agree.
"""
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy import ndimage
from scipy.stats import spearmanr

from config import MIN_SOURCE_HA, RAW, WORK

NEVER = 255


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    shape = (g["height"], g["width"])
    tf = from_origin(g["x0"], g["y1"], g["res"], g["res"])
    crs = f"EPSG:{g['epsg']}"
    storm = fire["usgs"]["design_storm"].replace("mm", "")       # peak 15-minute rainfall intensity, mm per hour
    basins = gpd.read_file(RAW / "usgs" / "basins.shp").to_crs(crs)
    segs = gpd.read_file(RAW / "usgs" / "segments.shp").to_crs(crs)
    lab = rasterize([(geom, i + 1) for i, geom in enumerate(basins.geometry)], out_shape=shape, transform=tf, dtype="int32")
    idx = range(1, len(basins) + 1)
    red = rasterio.open(WORK / "red_pass.tif").read(1) != NEVER
    scar = rasterio.open(WORK / "scar_pass.tif").read(1) != NEVER
    change = rasterio.open(WORK / "radar_change_db.tif").read(1)
    cells = ndimage.sum(np.ones(shape), lab, idx)
    basins["cells"] = cells
    basins["red_ha"] = ndimage.sum(red, lab, idx) * g["res"] ** 2 / 1e4
    basins["red_share"] = ndimage.sum(red, lab, idx) / np.maximum(cells, 1)
    basins["scar_share"] = ndimage.sum(scar, lab, idx) / np.maximum(cells, 1)
    basins["radar_db"] = ndimage.mean(np.nan_to_num(change), lab, idx)
    b = basins[basins["cells"] >= 5]          # a few basins are smaller than a handful of 30 m cells
    H, P = f"H_{storm}", f"P_{storm}"
    flagged = b["red_ha"] >= MIN_SOURCE_HA
    serious = b[H] >= 2

    def rho(x, y):
        r = spearmanr(x, y)
        return {"spearman": round(float(r.statistic), 2), "p": float(f"{r.pvalue:.1g}")}

    # Homes we flag: how close is the nearest stream segment USGS rates Moderate or High?
    st = gpd.read_file(WORK / "structures_zoned.gpkg")
    ours = st[st["home"] & (st["k"] != NEVER)]
    hot = segs[segs[H] >= 2]
    near_usgs = int((ours.geometry.apply(lambda p: hot.distance(p).min() if len(hot) else np.inf) <= 150).sum()) if len(ours) else 0
    anyseg = int((ours.geometry.apply(lambda p: segs.distance(p).min()) <= 150).sum()) if len(ours) else 0

    out = {
        "design_storm_mm_h": int(storm), "n_basins": int(len(b)),
        "radar_vs_severity": rho(-b["radar_db"], b["Fire_M1"]),
        "red_vs_terrain": rho(b["red_share"], b["Terrain_M1"]),
        "red_vs_likelihood": rho(b["red_share"], b[P]),
        "scar_vs_burnratio": rho(b["scar_share"], b["BurnRatio"]),
        "mean_red_share": round(float((b["red_share"] * b["cells"]).sum() / b["cells"].sum()), 3),
        "mean_terrain_term": round(float((b["Terrain_M1"] * b["cells"]).sum() / b["cells"].sum()), 3),
        "usgs_hazard_counts": {k: int(v) for k, v in b[f"{H}_LG"].value_counts().items()},
        "table": {"both": int((flagged & serious).sum()), "only_ours": int((flagged & ~serious).sum()),
                  "only_usgs": int((~flagged & serious).sum()), "neither": int((~flagged & ~serious).sum())},
        "homes_flagged": int(len(ours)), "homes_flagged_near_usgs_segment": anyseg, "homes_flagged_near_usgs_moderate_high": near_usgs,
        "usgs_segments_moderate_high": int(len(hot)), "usgs_segments": int(len(segs)),
        "points": [[round(float(r), 3), round(float(t), 3), round(float(p), 3), int(hz)] for r, t, p, hz in zip(b["red_share"], b["Terrain_M1"], b[P], b[H])],
    }
    t = out["table"]
    out["agreement"] = round((t["both"] + t["neither"]) / len(b), 2)
    (WORK / "usgs_check.json").write_text(json.dumps(out, indent=1))

    # Layers for the map: basins and segments with the USGS result at the design storm.
    keep = {H: "h", P: "p", f"V_{storm}": "v"}
    bb = basins[list(keep) + ["red_share", "geometry"]].rename(columns=keep)
    bb["geometry"] = bb.geometry.simplify(10)
    bb.to_crs(4326).to_file(WORK / "usgs_basins.geojson", driver="GeoJSON")
    ss = segs[list(keep) + ["geometry"]].rename(columns=keep)
    ss["geometry"] = ss.geometry.simplify(10)
    ss.to_crs(4326).to_file(WORK / "usgs_segments.geojson", driver="GeoJSON")
    print(json.dumps({k: v for k, v in out.items() if k != "points"}, indent=1))


if __name__ == "__main__":
    main()
