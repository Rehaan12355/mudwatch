"""Step 6: red zones, the paths below them, and who is in the way.

Red zone   = ground the radar says burned AND that is STEEP_DEG or steeper.
Mud path   = the channel below a red zone, followed downhill until the ground
             flattens out, drawn PATH_HALF_WIDTH_M wide either side.
In the way = homes whose centre sits inside a red zone or a mud path.

How a path is drawn
1. Water (and mud) is sent from each cell to its lowest neighbour, after
   filling the small pits every elevation model has.
2. Each cell learns how much red zone lies upstream of it. A path starts
   where that reaches MIN_SOURCE_HA.
3. The path carries on downhill. It ends once the channel has stayed flatter
   than RUNOUT_STOP_DEG for RUNOUT_FLAT_M, or RUNOUT_MAX_M below the last red
   cell that feeds it, whichever comes first.

This is a screen, not a debris-flow model: it knows nothing about rainfall,
soil or how much material a slope can shed. It is repeated for every radar
pass, so the site can show the zones growing as the scar was mapped.
"""
import heapq
import json

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import shapes
from rasterio.transform import from_origin, rowcol
from scipy import ndimage
from shapely.geometry import shape as to_shape

from config import (FIRE, MIN_SOURCE_HA, NEAR_PATH_M, PATH_HALF_WIDTH_M, RUNOUT_FLAT_M, RUNOUT_MAX_M, RUNOUT_STOP_DEG, STEEP_DEG, WORK)

NEVER = 255
NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def fill(dem):
    """Priority-flood pit filling with a tiny slope added, so every cell has a lower neighbour to drain to."""
    h, w = dem.shape
    out = dem.astype("float64").copy()
    done = np.zeros((h, w), bool)
    heap = []
    for r in range(h):
        for c in ((0, w - 1) if 0 < r < h - 1 else range(w)):
            heapq.heappush(heap, (out[r, c], r, c))
            done[r, c] = True
    while heap:
        z, r, c = heapq.heappop(heap)
        for dr, dc in NB:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and not done[rr, cc]:
                done[rr, cc] = True
                if out[rr, cc] <= z:
                    out[rr, cc] = z + 1e-3
                heapq.heappush(heap, (out[rr, cc], rr, cc))
    return out


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    res = g["res"]
    h, w = g["height"], g["width"]
    n = h * w
    tf = from_origin(g["x0"], g["y1"], res, res)
    crs = f"EPSG:{g['epsg']}"
    dem = rasterio.open(WORK / "dem.tif").read(1)
    slope = rasterio.open(WORK / "slope.tif").read(1)
    first = rasterio.open(WORK / "scar_pass.tif").read(1)
    scar = json.loads((WORK / "scar.json").read_text())
    K = len(scar["passes"])
    steep = slope >= STEEP_DEG

    # --- 1. where each cell drains ------------------------------------------------
    z = fill(dem)
    p = np.pad(z, 1, constant_values=np.inf)
    drops = np.stack([(z - p[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]) / (res * np.hypot(dr, dc)) for dr, dc in NB])
    best = drops.argmax(0)
    has = drops.max(0) > 0
    rr, cc = np.mgrid[0:h, 0:w]
    down = np.where(has, (rr + np.array([d[0] for d in NB])[best]) * w + cc + np.array([d[1] for d in NB])[best], -1).ravel()
    step = (res * np.hypot(*np.array(NB)[best].T.reshape(2, h, w))).ravel()
    order = np.argsort(-z.ravel(), kind="stable")   # highest first: every cell comes before the cell it drains to
    # Channel gradient, measured over the next five cells downstream so single-cell noise does not end a path.
    zz = z.ravel()
    far, run = np.arange(n), np.zeros(n)
    for _ in range(5):
        nxt = np.where(down[far] >= 0, down[far], far)
        run += np.where(nxt != far, step[far], 0)
        far = nxt
    grade = np.degrees(np.arctan((zz - zz[far]) / np.maximum(run, 1)))

    # --- 2. red zone upstream of every cell, after every pass ------------------------
    red_first = np.where(steep, first, NEVER).ravel()            # pass at which a cell turned red
    upstream = np.zeros((n, K), "int32")
    hit = np.flatnonzero(red_first != NEVER)
    upstream[hit, red_first[hit]] = 1
    np.cumsum(upstream, axis=1, out=upstream)
    for c in order:
        d = down[c]
        if d >= 0:
            upstream[d] += upstream[c]
    need = int(np.ceil(MIN_SOURCE_HA * 1e4 / res**2))
    loaded_any = np.flatnonzero(upstream[:, -1] >= need)
    seq = order[np.isin(order, loaded_any)]

    # --- 3. follow the paths, once per pass ---------------------------------------------
    path_first = np.full(n, NEVER, "uint8")
    for k in range(K):
        A = upstream[:, k]
        alive = {}                      # cell -> (metres below the last red cell, metres of flat channel so far)
        inflow = {}                     # best state handed down by path cells upstream
        for c in seq:
            if A[c] < need:
                continue
            src = inflow.pop(c, None)
            red_here = red_first[c] <= k
            if src is None:
                state = (0.0, 0.0)      # head of a path
            else:
                dist = 0.0 if red_here else src[0] + step[c]
                flat = 0.0 if grade[c] >= RUNOUT_STOP_DEG else src[1] + step[c]
                if dist > RUNOUT_MAX_M or flat > RUNOUT_FLAT_M:
                    state = None
                else:
                    state = (dist, flat)
            d = down[c]
            if state is None:
                # A dead path stays dead: mark the cell below so it is not mistaken for a fresh head.
                if d >= 0 and d not in inflow:
                    inflow[d] = (np.inf, np.inf)
                continue
            alive[c] = state
            if path_first[c] == NEVER:
                path_first[c] = k
            if d >= 0:
                o = inflow.get(d)
                inflow[d] = state if o is None else (min(o[0], state[0]), min(o[1], state[1]))
    path_first = path_first.reshape(h, w)
    red_first = red_first.reshape(h, w)

    # Width: the channel plus PATH_HALF_WIDTH_M either side. Each widened cell takes the earliest pass of the cells it widens.
    r_cells = max(1, int(round(PATH_HALF_WIDTH_M / res)))
    zone_first = ndimage.minimum_filter(path_first, size=2 * r_cells + 1)
    zone_first = np.minimum(zone_first, red_first)          # being in a red zone counts as well
    zone = zone_first != NEVER
    near = (ndimage.distance_transform_edt(~zone) * res <= NEAR_PATH_M) & ~zone

    prof = dict(driver="GTiff", height=h, width=w, count=1, dtype="uint8", crs=crs, transform=tf, nodata=NEVER, compress="deflate")
    for name, a in (("red_pass", red_first), ("path_pass", path_first), ("zone_pass", zone_first)):
        with rasterio.open(WORK / f"{name}.tif", "w", **prof) as dst:
            dst.write(a.astype("uint8"), 1)
    with rasterio.open(WORK / "upstream_red_ha.tif", "w", **dict(prof, dtype="float32", nodata=np.nan)) as dst:
        dst.write((upstream[:, -1].reshape(h, w) * res**2 / 1e4).astype("float32"), 1)

    # --- 4. homes and people ------------------------------------------------------------
    st = gpd.read_file(WORK / "structures.gpkg").to_crs(crs)
    rows, cols = rowcol(tf, st.geometry.x.values, st.geometry.y.values)
    rows, cols = np.asarray(rows), np.asarray(cols)
    inwin = (rows >= 0) & (rows < h) & (cols >= 0) & (cols < w)
    st = st[inwin].copy()
    rows, cols = rows[inwin], cols[inwin]
    st["k"] = zone_first[rows, cols]
    st["near"] = near[rows, cols]
    st["in_scar"] = first[rows, cols] != NEVER
    st.to_file(WORK / "structures_zoned.gpkg", driver="GPKG")
    homes = st[st["home"]]

    def tally(k):
        m = homes["k"] <= k
        return int(m.sum()), float(homes.loc[m, "people"].sum())

    cell_km2 = res**2 / 1e6
    steps = []
    for k, ps in enumerate(scar["passes"]):
        nh, npeople = tally(k)
        steps.append({"date": ps["date"], "red_km2": round(float((red_first <= k).sum() * cell_km2), 3),
                      "path_km": round(float((path_first <= k).sum() * res / 1000), 1), "homes": nh, "people": round(npeople)})

    # Roads inside the zone.
    polys = [to_shape(s) for s, v in shapes(zone.astype("uint8"), mask=zone, transform=tf)]
    zone_gdf = gpd.GeoDataFrame(geometry=polys, crs=crs)
    zone_gdf.to_file(WORK / "zone.gpkg", driver="GPKG")
    roads = gpd.read_file(WORK / "roads.gpkg").to_crs(crs)
    public = roads[roads["highway"].isin(["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"])]
    cut = gpd.overlay(public[["name", "highway", "geometry"]], gpd.GeoDataFrame(geometry=[zone_gdf.union_all()], crs=crs), how="intersection", keep_geom_type=True) if len(public) else public
    road_km = float(cut.length.sum() / 1000) if len(cut) else 0.0
    road_names = cut.assign(len=cut.length).groupby("name")["len"].sum().sort_values(ascending=False) if len(cut) else {}

    # --- 5. per block ---------------------------------------------------------------------
    blocks = gpd.read_file(WORK / "blocks.gpkg").to_crs(crs)
    per = {}
    for bid, grp in homes.groupby("block"):
        inz = grp[grp["k"] != NEVER]
        per[bid] = {"homes_in": len(inz), "people_in": float(inz["people"].sum()), "homes_near": int(grp["near"].sum()),
                    "people_near": float(grp.loc[grp["near"], "people"].sum()), "homes_in_window": len(grp),
                    "k": int(inz["k"].min()) if len(inz) else None}
    blocks["stats"] = blocks["GEOID"].map(per)
    (WORK / "block_stats.json").write_text(json.dumps(per))

    nh, npeople = tally(K - 1)
    out = {
        "rule": {"steep_deg": STEEP_DEG, "min_source_ha": MIN_SOURCE_HA, "runout_stop_deg": RUNOUT_STOP_DEG, "runout_flat_m": RUNOUT_FLAT_M,
                 "runout_max_m": RUNOUT_MAX_M, "path_half_width_m": PATH_HALF_WIDTH_M, "near_path_m": NEAR_PATH_M},
        "passes": steps,
        "scar_km2": round(float((first != NEVER).sum() * cell_km2), 2),
        "steep_share_of_scar": round(float((steep & (first != NEVER)).sum() / max(1, (first != NEVER).sum())), 3),
        "red_km2": steps[-1]["red_km2"], "path_km": steps[-1]["path_km"], "zone_km2": round(float(zone.sum() * cell_km2), 2),
        "homes_in_zone": nh, "people_in_zone": round(npeople),
        "homes_near": int(homes["near"].sum()), "people_near": round(float(homes.loc[homes["near"], "people"].sum())),
        "homes_in_scar": int(homes["in_scar"].sum()),
        "other_buildings_in_zone": int(((st["k"] != NEVER) & ~st["home"]).sum()),
        "homes_in_window": len(homes), "people_in_window": round(float(homes["people"].sum())),
        "road_km_in_zone": round(road_km, 1),
        "roads_in_zone": [{"name": nme, "km": round(v / 1000, 2)} for nme, v in list(getattr(road_names, "items", lambda: [])())[:8] if v >= 50],
        "blocks_with_homes_in_zone": sum(1 for v in per.values() if v["homes_in"]),
    }
    (WORK / "zones.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "passes"}, indent=1))
    for s in steps[::4] + steps[-1:]:
        print(s)


if __name__ == "__main__":
    main()
