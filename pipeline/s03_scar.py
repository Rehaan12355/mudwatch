"""Step 3: the burn scar, as radar saw it grow.

A forest that burns loses the leaves and small branches that scatter radar
back to the satellite, so burned ground goes darker in the cross-polarized
(VH) channel. For every pass after ignition we compare the picture with that
track's own "before" picture and flag ground that went clearly darker.

One look is not trusted: speckle, rain and wet ground move the signal too. A
cell joins the scar only when LOOKS passes in a row agree, which is the same
idea NASA's DIST-ALERT products use for their confirmed alerts. Fields and
bare ground darken and brighten with the seasons, so only ground that looked
tree-covered to the radar before the fire is allowed to join.

Outputs
- scar_pass.tif   for each cell, the index of the pass that confirmed it (255 = never)
- scar.json       area confirmed after each pass, and a check against the official perimeter

The perimeter is used only to score the result, never to make it.
"""
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from scipy import ndimage

from config import WORK

SMOOTH = 5          # 5 x 5 cells (150 m) averaged before comparing, to calm speckle
LOOKS = 3           # passes in a row that must agree
DROP_DB = 1.25      # their average must be this much darker than "before"...
EACH_DB = DROP_DB / 2   # ...and every one of them at least this much darker
FOREST_DB = -16.0   # only ground this bright before the fire (tree cover, to a C-band radar) can join the scar
MIN_PATCH_HA = 2.0  # smaller isolated patches are dropped
NEVER = 255


def smooth(a):
    ok = np.isfinite(a)
    s = ndimage.uniform_filter(np.where(ok, a, 0.0), SMOOTH)
    n = ndimage.uniform_filter(ok.astype("float32"), SMOOTH)
    return np.where(n > 0.5, s / np.maximum(n, 1e-6), np.nan)


def detect(looks, forest):
    """looks: chronological list of (pass index, change in dB). Returns the confirming pass per cell."""
    first = np.full(forest.shape, NEVER, "uint8")
    recent = []
    for idx, d in looks:
        recent = (recent + [d])[-LOOKS:]
        if len(recent) < LOOKS:
            continue
        st = np.stack(recent)
        with np.errstate(all="ignore"):
            hit = forest & np.isfinite(st).all(0) & (st.mean(0) <= -DROP_DB) & (st <= -EACH_DB).all(0)
        first[hit & (first == NEVER)] = idx
    # A burn scar is one or more solid patches: drop specks.
    lab, n = ndimage.label(first != NEVER)
    if n:
        size = ndimage.sum(np.ones(forest.shape), lab, range(1, n + 1))
        first[np.isin(lab, 1 + np.flatnonzero(size * 0.09 < MIN_PATCH_HA))] = NEVER
    return first


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    shape = (g["height"], g["width"])
    tf = from_origin(g["x0"], g["y1"], g["res"], g["res"])
    passes = json.loads((WORK / "passes.json").read_text())
    start = fire["usgs"]["start_date"].replace("-", "")

    def vh(p):
        return smooth(np.load(WORK / "rtc" / f"{p['date']}_T{p['track']}.npz")["VH"])

    change = {}   # pass position -> dB change against its own track's "before" picture
    befores = []
    for track in sorted({p["track"] for p in passes}):
        mine = [(i, p) for i, p in enumerate(passes) if p["track"] == track]
        pre = [vh(p) for i, p in mine if p["date"] < start]
        if len(pre) < 3:
            print("track", track, "has too few passes before the fire; skipped")
            continue
        with np.errstate(all="ignore"):
            before = 10 * np.log10(np.nanmean(pre, axis=0))
            befores.append(before)
            for i, p in mine:
                d = 10 * np.log10(vh(p)) - before
                change[i] = (d - np.nanmedian(d)).astype("float32")   # the whole scene brightens and darkens with rain; remove that
        print("track", track, len(pre), "before,", sum(1 for i, p in mine if p["date"] >= start), "after")

    post = [i for i, p in enumerate(passes) if p["date"] >= start and i in change]
    with np.errstate(all="ignore"):
        forest = np.nanmean(befores, axis=0) >= FOREST_DB
    first = detect([(k, change[i]) for k, i in enumerate(post)], forest)

    # --- check -----------------------------------------------------------------
    perim = gpd.read_file(WORK / "perimeter.gpkg")
    inside = rasterize([(perim.geometry[0], 1)], out_shape=shape, transform=tf, dtype="uint8") == 1
    scar = first != NEVER
    km2 = lambda m: round(float(m.sum() * 0.0009), 2)
    # False-alarm test: run the same detector on the passes before the fire, when nothing had burned.
    # Each track's "before" picture is rebuilt without the passes being tested.
    pre_idx = [i for i, p in enumerate(passes) if p["date"] < start and i in change]
    half = len(pre_idx) // 2
    looks = []
    for track in sorted({passes[i]["track"] for i in pre_idx}):
        early = [i for i in pre_idx[:half] if passes[i]["track"] == track]
        late = [i for i in pre_idx[half:] if passes[i]["track"] == track]
        if len(early) < 2 or not late:
            continue
        with np.errstate(all="ignore"):
            before = 10 * np.log10(np.nanmean([vh(passes[i]) for i in early], axis=0))
            for i in late:
                d = 10 * np.log10(vh(passes[i])) - before
                looks.append((i, d - np.nanmedian(d)))
    false = detect([(k, d) for k, (i, d) in enumerate(sorted(looks, key=lambda x: x[0]))], forest) != NEVER

    steps = []
    for k, i in enumerate(post):
        p = passes[i]
        got = first <= k
        steps.append({"date": f"{p['date'][:4]}-{p['date'][4:6]}-{p['date'][6:]}", "time_utc": p["time_utc"][:2] + ":" + p["time_utc"][2:4],
                      "track": p["track"], "satellite": p["satellite"], "scar_km2": km2(got), "inside_km2": km2(got & inside)})
    out = {
        "method": {"smooth_cells": SMOOTH, "drop_db": DROP_DB, "each_db": EACH_DB, "looks": LOOKS, "forest_db": FOREST_DB, "min_patch_ha": MIN_PATCH_HA, "polarization": "VH"},
        "passes": steps,
        "n_before": len(pre_idx),
        "check": {
            "perimeter_km2": km2(inside), "scar_km2": km2(scar),
            "scar_inside_km2": km2(scar & inside), "scar_outside_km2": km2(scar & ~inside),
            "share_of_perimeter_detected": round(float((scar & inside).sum() / inside.sum()), 3),
            "share_of_scar_inside_perimeter": round(float((scar & inside).sum() / max(1, scar.sum())), 3),
            "prefire_false_alarm_km2": km2(false), "prefire_test_looks": len(looks),
            "window_km2": km2(np.ones(shape, bool)), "tree_cover_share_of_window": round(float(forest.mean()), 3),
        },
    }
    first_seen = next((s for s in steps if s["inside_km2"] >= 1.0), None)
    out["check"]["first_km2_inside_date"] = first_seen["date"] if first_seen else None
    (WORK / "scar.json").write_text(json.dumps(out, indent=1))
    # Mean change over the latest passes, kept for the comparison with the USGS burn-severity term.
    with np.errstate(all="ignore"):
        late = np.nanmean([change[i] for i in post[-12:]], axis=0).astype("float32")
    with rasterio.open(WORK / "radar_change_db.tif", "w", driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="float32",
                       crs=f"EPSG:{g['epsg']}", transform=tf, nodata=np.nan, compress="deflate") as dst:
        dst.write(late, 1)
    with rasterio.open(WORK / "scar_pass.tif", "w", driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="uint8",
                       crs=f"EPSG:{g['epsg']}", transform=tf, nodata=NEVER, compress="deflate") as dst:
        dst.write(first, 1)
    for s in steps:
        print(s["date"], "T" + s["track"], s["satellite"], f"{s['scar_km2']:6.2f} km2, inside perimeter {s['inside_km2']:6.2f}")
    print(json.dumps(out["check"], indent=1))


if __name__ == "__main__":
    main()
