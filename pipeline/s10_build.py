"""Step 10: package everything the website needs into site/data/<fire>/.

Outputs
- fire.json           every number the site shows, with the pass-by-pass timeline
- layers.png          per cell: R = pass that confirmed the burn, G = pass it turned red, B = pass a mud path reached it (255 = never)
- terrain.png         per cell: R = slope in degrees, G = hillshade
- radar.png           Sentinel-1 backscatter on the pass nearest the smoky optical picture
- nisar_before.png, nisar_after.png   NISAR L-band backscatter
- optical.jpg         written by step 9
- homes.geojson, blocks.geojson, perimeter.geojson, usgs_basins.geojson, usgs_segments.geojson
"""
import json

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin, rowcol
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds
from scipy import ndimage

from common import write_sources_md
from config import FIRE, FIRES, SITE_DATA, STEEP_DEG, WORK

NEVER = 255


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    h, w = g["height"], g["width"]
    tf = from_origin(g["x0"], g["y1"], g["res"], g["res"])
    crs = f"EPSG:{g['epsg']}"
    load = lambda n: json.loads((WORK / n).read_text()) if (WORK / n).exists() else None
    scar, zones, check, nisar, optical, people, dist, passes = (load(n) for n in ("scar.json", "zones.json", "usgs_check.json", "nisar.json", "optical.json", "people.json", "dist.json", "passes.json"))

    # One Web Mercator grid for every picture, so the browser can stack them cell for cell.
    wtf, ww, wh = calculate_default_transform(crs, "EPSG:3857", w, h, *rasterio.transform.array_bounds(h, w, tf))
    bounds = [round(v, 6) for v in transform_bounds("EPSG:3857", "EPSG:4326", *rasterio.transform.array_bounds(wh, ww, wtf))]

    def web(a, resampling, nodata):
        out = np.full((wh, ww), nodata, a.dtype)
        reproject(a, out, src_transform=tf, src_crs=crs, dst_transform=wtf, dst_crs="EPSG:3857", resampling=resampling, src_nodata=nodata, dst_nodata=nodata)
        return out

    read = lambda n: rasterio.open(WORK / n).read(1)
    rgba = np.full((wh, ww, 4), 255, np.uint8)
    for c, name in enumerate(("scar_pass.tif", "red_pass.tif", "zone_pass.tif")):
        rgba[..., c] = web(read(name), Resampling.nearest, NEVER)
    Image.fromarray(rgba, "RGBA").save(SITE_DATA / "layers.png", optimize=True)

    dem, slope = read("dem.tif"), read("slope.tif")
    gy, gx = np.gradient(dem, g["res"])
    shade = np.clip(0.5 + 0.9 * (gx - gy) / np.sqrt(1 + gx**2 + gy**2), 0, 1)      # light from the north-west
    terr = np.full((wh, ww, 4), 255, np.uint8)
    terr[..., 0] = np.nan_to_num(np.clip(web(slope, Resampling.bilinear, np.nan), 0, 90)).round()
    terr[..., 1] = np.nan_to_num(web(shade.astype("float32"), Resampling.bilinear, np.nan) * 255, nan=127).round()
    terr[..., 2] = 0
    Image.fromarray(terr, "RGBA").save(SITE_DATA / "terrain.png", optimize=True)

    def grey(a, lo, hi, name):
        v = np.clip((web(a.astype("float32"), Resampling.bilinear, np.nan) - lo) / (hi - lo), 0, 1)
        Image.fromarray((np.nan_to_num(v) * 255).astype("uint8"), "L").save(SITE_DATA / name, optimize=True)

    # Radar picture nearest the optical one, from the track that covers the whole window.
    radar_pic = None
    if passes:
        target = (optical or {}).get("date", fire["usgs"]["start_date"]).replace("-", "")
        full = [p for p in passes if p["coverage"] > 0.98 and p["date"] >= fire["usgs"]["start_date"].replace("-", "")]
        p = min(full, key=lambda p: abs(int(p["date"]) - int(target)))
        with np.errstate(all="ignore"):
            grey(10 * np.log10(np.load(WORK / "rtc" / f"{p['date']}_T{p['track']}.npz")["VH"]), -24, -9, "radar.png")
        radar_pic = {"date": f"{p['date'][:4]}-{p['date'][4:6]}-{p['date'][6:]}", "time_utc": p["time_utc"][:2] + ":" + p["time_utc"][2:4], "satellite": p["satellite"], "track": p["track"]}
    if nisar and nisar.get("ok"):
        nb = read("nisar_before_db.tif")
        lo, hi = (float(v) for v in np.nanpercentile(nb, [1, 99.5]))     # one stretch for both, set by the "before" picture
        grey(nb, lo, hi, "nisar_before.png")
        grey(read("nisar_after_db.tif"), lo, hi, "nisar_after.png")

    # --- vectors ----------------------------------------------------------------------
    def dump(gdf, name, digits=5):
        def rnd(o):
            if isinstance(o, float):
                return round(o, digits)
            if isinstance(o, (list, tuple)):
                return [rnd(x) for x in o]
            if isinstance(o, dict):
                return {k: rnd(v) for k, v in o.items()}
            return o
        (SITE_DATA / name).write_text(json.dumps(rnd(json.loads(gdf.to_crs(4326).to_json(drop_id=True))), separators=(",", ":")))

    perim = gpd.read_file(WORK / "perimeter.gpkg")
    dump(perim.assign(geometry=perim.simplify(10)), "perimeter.geojson")
    for n in ("usgs_basins.geojson", "usgs_segments.geojson"):
        dump(gpd.read_file(WORK / n), n)

    st = gpd.read_file(WORK / "structures_zoned.gpkg")
    homes = st[st["home"]].copy()
    up = ndimage.maximum_filter(read("upstream_red_ha.tif"), size=3)
    rows, cols = rowcol(tf, homes.geometry.x.values, homes.geometry.y.values)
    homes["up_ha"] = up[np.asarray(rows), np.asarray(cols)]
    homes["k"] = homes["k"].where(homes["k"] != NEVER, -1).astype(int)
    hg = homes[["k", "block", "geometry"]].rename(columns={"block": "b"}).copy()
    hg["near"] = homes["near"].astype(int)
    dump(hg, "homes.geojson")

    blocks = gpd.read_file(WORK / "blocks.gpkg").to_crs(crs)
    stats = load("block_stats.json")
    scar_cells = read("scar_pass.tif") != NEVER
    feats = []
    for _, b in blocks.iterrows():
        s = stats.get(b["GEOID"], {})
        mine = homes[homes["block"] == b["GEOID"]]
        inz = mine[mine["k"] >= 0]
        name = b["road"] if isinstance(b["road"], str) else f"Census block {b['GEOID'][-4:]}"
        status = "in" if s.get("homes_in") else "near" if s.get("homes_near") else "clear" if len(mine) else "empty"
        feats.append({
            "id": b["GEOID"], "name": name, "place": b["place"] if isinstance(b["place"], str) else None,
            "place_km": None if b["place_km"] is None or np.isnan(b["place_km"]) else float(b["place_km"]),
            "pop": int(b["pop"]), "homes": len(mine), "homes_in": int(s.get("homes_in", 0)), "people_in": round(s.get("people_in", 0.0)),
            "homes_near": int(s.get("homes_near", 0)), "people_near": round(s.get("people_near", 0.0)),
            "k": s.get("k") if s.get("k") is not None else -1, "status": status,
            "up_ha": round(float(inz["up_ha"].max()), 1) if len(inz) else 0.0,
        })
    bg = gpd.GeoDataFrame(feats, geometry=blocks.simplify(8).values, crs=crs)
    dump(bg, "blocks.geojson")

    # --- the timeline ---------------------------------------------------------------------
    timeline = [dict(a, **{k: b[k] for k in ("red_km2", "path_km", "homes", "people")}) for a, b in zip(scar["passes"], zones["passes"])]
    first = lambda key, floor=0: next((t["date"] for t in timeline if t[key] > floor), None)
    out = {
        "id": FIRE["id"], "name": FIRE["name"], "short_name": FIRE["short_name"], "state": FIRE["state"], "county": FIRE["county"],
        "why": FIRE["why"], "nws_office": FIRE["nws_office"], "nws_url": FIRE["nws_url"],
        "bounds": bounds, "focus": [round(float(v), 4) for v in perim.to_crs(4326).total_bounds],
        "usgs": fire["usgs"], "perimeter_km2": fire["perimeter_km2"],
        "steep_deg": STEEP_DEG, "rule": zones["rule"], "scar_method": scar["method"], "scar_check": scar["check"], "passes_before": scar["n_before"],
        "timeline": timeline,
        "dates": {"ignition": fire["usgs"]["start_date"], "first_pass": timeline[0]["date"], "first_scar": first("scar_km2"),
                  "first_red": first("red_km2"), "first_home": first("homes"), "usgs_assessment": fire["usgs"]["assessment_date"],
                  "latest_pass": timeline[-1]["date"]},
        "totals": {k: zones[k] for k in ("scar_km2", "steep_share_of_scar", "red_km2", "path_km", "zone_km2", "homes_in_zone", "people_in_zone", "homes_near", "people_near",
                                        "other_buildings_in_zone", "homes_in_window", "people_in_window", "road_km_in_zone", "roads_in_zone", "blocks_with_homes_in_zone")},
        "people": people, "usgs_check": check, "nisar": nisar, "optical": optical, "radar_picture": radar_pic, "dist": dist,
    }
    (SITE_DATA / "fire.json").write_text(json.dumps(out, separators=(",", ":")))
    built = [{"id": fid, "name": f["name"], "short_name": f["short_name"]} for fid, f in FIRES.items() if (SITE_DATA.parent / fid / "fire.json").exists()]
    (SITE_DATA.parent / "fires.json").write_text(json.dumps(built))
    write_sources_md()
    for f in sorted(SITE_DATA.iterdir()):
        print(f"{f.name:22s} {f.stat().st_size / 1e6:6.2f} MB")
    print(json.dumps(out["dates"], indent=1))
    print("status counts:", bg["status"].value_counts().to_dict(), "picture", ww, "x", wh)


if __name__ == "__main__":
    main()
