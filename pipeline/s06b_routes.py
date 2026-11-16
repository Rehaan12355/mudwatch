"""Step 6b: ways out by road, and the places to clear before the rain.

Neither of these is an official product. There is no public evacuation-route
map and no inventory of debris basins for these fires, so both are worked out
from OpenStreetMap roads and the mud paths of step 6, and the site says so.

Way out        = the cheapest drive from each home in a possible mud path to a
                 main road (a state highway, or a through road at the edge of
                 the map) that is clear of every mapped path. Road inside a
                 path costs ZONE_COST times its length, so a route only runs
                 through a path when the detour would be far longer. The parts
                 of a route that do lie in a path are kept apart: that is road
                 mud could cut.
Clearing point = where a mud path's channel crosses a public road. That is
                 where a culvert or ditch would plug and mud would spill onto
                 the road. Crossings closer than CLUSTER_M count as one.
                 Any basin OpenStreetMap maps in the window is added as well.
"""
import json
from collections import defaultdict

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin, rowcol, xy
from scipy import ndimage
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, unary_union

from common import record_source
from config import FIRE, RAW, WORK
from s05_people import OVERPASS, overpass
from s06_zones import NB, NEVER, fill

PUBLIC = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"}
MAIN = {"motorway", "trunk", "primary", "secondary"}
THROUGH = {"tertiary"}
CLASS_COST = {"track": 4.0, "service": 1.3}     # forest tracks and driveways are slower than their length suggests
ZONE_COST = 5.0          # a metre of road inside a mud path counts as this many metres
CLEAR_M = 1000           # a way out ends on a main road at least this far from every path
EDGE_M = 250             # "at the edge of the map"
SNAP_M = 400             # a home further than this from any mapped road gets no route
CLUSTER_M = 120          # crossings closer than this are one clearing point


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    res, h, w = g["res"], g["height"], g["width"]
    tf = from_origin(g["x0"], g["y1"], res, res)
    crs = f"EPSG:{g['epsg']}"
    to_utm = Transformer.from_crs(4326, crs, always_xy=True)
    zone_first = rasterio.open(WORK / "zone_pass.tif").read(1)
    path_first = rasterio.open(WORK / "path_pass.tif").read(1)
    up_ha = rasterio.open(WORK / "upstream_red_ha.tif").read(1)
    zone = zone_first != NEVER
    zone_dist = ndimage.distance_transform_edt(~zone) * res
    zone_poly = gpd.read_file(WORK / "zone.gpkg").union_all()

    def cell(x, y):
        r, c = rowcol(tf, x, y)
        return np.clip(r, 0, h - 1), np.clip(c, 0, w - 1)

    # --- the road network ---------------------------------------------------------------
    ways = json.loads((RAW / "osm_roads.json").read_text())["elements"]
    nid, pts = {}, []
    ea, eb, elen, ecost, eway = [], [], [], [], []
    for wi, wy in enumerate(ways):
        hw = wy["tags"]["highway"].replace("_link", "")
        xs, ys = to_utm.transform([p["lon"] for p in wy["geometry"]], [p["lat"] for p in wy["geometry"]])
        ids = []
        for n, x, y in zip(wy["nodes"], xs, ys):
            if n not in nid:
                nid[n] = len(pts)
                pts.append((x, y))
            ids.append(nid[n])
        for a, b in zip(ids[:-1], ids[1:]):
            (ax, ay), (bx, by) = pts[a], pts[b]
            d = float(np.hypot(bx - ax, by - ay))
            if d == 0:
                continue
            # Share of this stretch inside a mud path, sampled every 10 m.
            t = np.linspace(0, 1, max(2, int(d / 10) + 1))
            inz = float(zone[cell(ax + (bx - ax) * t, ay + (by - ay) * t)].mean())
            ea.append(a); eb.append(b); elen.append(d); eway.append(wi)
            ecost.append(d * CLASS_COST.get(hw, 1.0) * (1 + (ZONE_COST - 1) * inz))
    pts = np.array(pts)
    n = len(pts)
    ea, eb, elen, ecost, eway = map(np.array, (ea, eb, elen, ecost, eway))
    graph = csr_matrix((np.r_[ecost, ecost], (np.r_[ea, eb], np.r_[eb, ea])), shape=(n, n))
    edge_of = {}
    for i, (a, b) in enumerate(zip(ea, eb)):
        for key in ((a, b), (b, a)):
            if key not in edge_of or ecost[i] < ecost[edge_of[key]]:
                edge_of[key] = i
    hw_of = np.array([wy["tags"]["highway"].replace("_link", "") for wy in ways])
    label_of = [wy["tags"].get("ref") or wy["tags"].get("name") for wy in ways]
    name_of = [wy["tags"].get("name") or wy["tags"].get("ref") for wy in ways]

    # --- where a way out may end ----------------------------------------------------------
    node_hw = defaultdict(set)
    for i in range(len(ea)):
        node_hw[ea[i]].add(hw_of[eway[i]]); node_hw[eb[i]].add(hw_of[eway[i]])
    r_, c_ = cell(pts[:, 0], pts[:, 1])
    clear = zone_dist[r_, c_] >= CLEAR_M
    x0, y1 = g["x0"], g["y1"]
    at_edge = (np.minimum.reduce([pts[:, 0] - x0, x0 + w * res - pts[:, 0], y1 - pts[:, 1], pts[:, 1] - (y1 - h * res)]) <= EDGE_M)
    on = lambda classes: np.array([bool(node_hw[i] & classes) for i in range(n)])
    targets = np.flatnonzero(clear & (on(MAIN) | (on(THROUGH) & at_edge)))
    tier = "a main road"
    if not len(targets):       # no highway in the window: any public road leaving the map
        targets = np.flatnonzero(clear & on(PUBLIC - {"residential"}) & at_edge)
        tier = "the edge of the map"
    if not len(targets):
        raise SystemExit("no road leaves this map clear of the mud paths")
    dist, pred, src = dijkstra(graph, directed=False, indices=targets, return_predecessors=True, min_only=True)

    # --- one route per home in a path -------------------------------------------------------
    st = gpd.read_file(WORK / "structures_zoned.gpkg").to_crs(crs)
    homes = st[st["home"] & (st["k"] != NEVER)]
    tree = cKDTree(pts)
    places = json.loads((RAW / "osm_places.json").read_text())["elements"] if (RAW / "osm_places.json").exists() else []
    pxy = np.array(to_utm.transform([p["lon"] for p in places], [p["lat"] for p in places])).T if places else np.zeros((0, 2))

    routes, no_route = {}, 0
    for _, hm in homes.iterrows():
        d, start = tree.query((hm.geometry.x, hm.geometry.y))
        if d > SNAP_M or not np.isfinite(dist[start]):
            no_route += 1
            continue
        edges, a = [], start
        while pred[a] >= 0:
            edges.append(edge_of[(a, pred[a])])
            a = pred[a]
        r = routes.setdefault(int(src[start]), {"edges": set(), "homes": 0, "people": 0.0, "blocks": defaultdict(lambda: [0, 0.0]), "longest": 0.0, "xy": []})
        r["xy"].append((hm.geometry.x, hm.geometry.y))
        r["edges"].update(edges)
        r["homes"] += 1
        r["people"] += hm["people"]
        km = float(elen[edges].sum() / 1000) if edges else 0.0
        b = r["blocks"][hm["block"]]
        b[0] += 1
        b[1] = max(b[1], km)
        r["longest"] = max(r["longest"], km)

    feats, summary, block_route = [], [], {}
    order = sorted(routes.items(), key=lambda kv: -kv[1]["homes"])
    for rid, (tnode, r) in enumerate(order):
        edges = sorted(r["edges"])
        line = linemerge([LineString([pts[ea[i]], pts[eb[i]]]) for i in edges]) if edges else None
        cut = line.intersection(zone_poly) if line is not None else None
        cut = linemerge(cut) if cut is not None and cut.geom_type == "MultiLineString" else cut
        crossings = 0 if cut is None or cut.is_empty else len(getattr(cut, "geoms", [cut]))
        cut_km = 0.0 if cut is None else cut.length / 1000
        if line is not None:
            feats.append({"r": rid, "cut": 0, "geometry": line.difference(zone_poly)})
            if crossings:
                feats.append({"r": rid, "cut": 1, "geometry": cut})
        # Named for the public road that carries most of it, and for the road it ends on.
        length = defaultdict(float)
        for i in edges:
            if name_of[eway[i]] and hw_of[eway[i]] in PUBLIC:
                length[name_of[eway[i]]] += elen[i]
        via = max(length, key=length.get) if length else None
        ends = [eway[i] for i in np.flatnonzero((ea == tnode) | (eb == tnode))]
        best = max(ends, key=lambda wi: (hw_of[wi] in MAIN, hw_of[wi] in THROUGH, label_of[wi] is not None))
        to = label_of[best]
        place = None
        if len(pxy):
            dd = np.hypot(*(pxy - pts[tnode]).T)
            j = int(dd.argmin())
            place = {"name": places[j]["tags"]["name"], "km": round(float(dd[j] / 1000), 1)}
        dx, dy = pts[tnode] - np.mean(r["xy"], axis=0)
        heading = ["east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east"][int(round(np.degrees(np.arctan2(dy, dx)) / 45)) % 8]
        lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(*pts[tnode])
        summary.append({"id": rid, "via": via, "to": to, "to_kind": "main" if hw_of[best] in MAIN else "edge", "place": place if place and place["km"] <= 3 else None, "heading": heading, "end": [round(lon, 5), round(lat, 5)],
                        "km": round(r["longest"], 1), "cut_km": round(cut_km, 2), "crossings": crossings, "homes": r["homes"], "people": round(r["people"])})
        for bid, (nh, km) in r["blocks"].items():
            if bid not in block_route or nh > block_route[bid]["homes"]:
                block_route[bid] = {"route": rid, "homes": nh, "km": round(km, 1)}
    route_gdf = gpd.GeoDataFrame(feats, crs=crs) if feats else gpd.GeoDataFrame({"r": [], "cut": []}, geometry=[], crs=crs)
    route_gdf = route_gdf[~route_gdf.geometry.is_empty]
    route_gdf.to_file(WORK / "routes.geojson", driver="GeoJSON")
    route_all = unary_union(route_gdf.geometry.values) if len(route_gdf) else None

    # --- clearing points: where a mud channel crosses a public road -------------------------------
    z = fill(rasterio.open(WORK / "dem.tif").read(1))
    p = np.pad(z, 1, constant_values=np.inf)
    drops = np.stack([(z - p[1 + dr:1 + dr + h, 1 + dc:1 + dc + w]) for dr, dc in NB])
    best = drops.argmax(0)
    chan_r, chan_c = np.nonzero((path_first != NEVER) & (drops.max(0) > 0))
    dr, dc = np.array(NB)[best[chan_r, chan_c]].T
    ok = (chan_r + dr >= 0) & (chan_r + dr < h) & (chan_c + dc >= 0) & (chan_c + dc < w)
    chan_r, chan_c, dr, dc = chan_r[ok], chan_c[ok], dr[ok], dc[ok]
    x_a, y_a = xy(tf, chan_r, chan_c)
    x_b, y_b = xy(tf, chan_r + dr, chan_c + dc)
    links = [LineString([(a, b), (c, d)]) for a, b, c, d in zip(x_a, y_a, x_b, y_b)]
    public = [(wi, LineString(np.array(to_utm.transform([q["lon"] for q in wy["geometry"]], [q["lat"] for q in wy["geometry"]])).T))
              for wi, wy in enumerate(ways) if hw_of[wi] in PUBLIC and len(wy["geometry"]) > 1]
    hits = []
    if links and public:
        tr = STRtree(links)
        for wi, line in public:
            for li in tr.query(line, predicate="intersects"):
                pt = line.intersection(links[li])
                pt = pt if pt.geom_type == "Point" else pt.representative_point()
                hits.append({"x": pt.x, "y": pt.y, "wi": wi, "ha": float(up_ha[chan_r[li], chan_c[li]]), "k": int(path_first[chan_r[li], chan_c[li]])})
    # Biggest first; anything within CLUSTER_M of a point already kept belongs to it.
    points = []
    for hit in sorted(hits, key=lambda q: -q["ha"]):
        if all(np.hypot(hit["x"] - q["x"], hit["y"] - q["y"]) > CLUSTER_M for q in points):
            points.append(hit)
    for q in points:
        q["k"] = min(o["k"] for o in hits if np.hypot(o["x"] - q["x"], o["y"] - q["y"]) <= CLUSTER_M)
        q["on_route"] = bool(route_all is not None and route_all.distance(Point(q["x"], q["y"])) <= 40)

    # Basins OpenStreetMap maps in the window. Usually none: it is checked so the site can say so.
    s, w_, n_, e_ = (round(v, 5) for v in (fire["bbox"][1], fire["bbox"][0], fire["bbox"][3], fire["bbox"][2])) if "bbox" in fire else (None,) * 4
    basins = []
    if s is not None:
        try:
            els = overpass("osm_basins.json", f'[out:json][timeout:90];(nwr["landuse"="basin"]({s},{w_},{n_},{e_});nwr["water"="basin"]({s},{w_},{n_},{e_});nwr["basin"]({s},{w_},{n_},{e_}););out center tags;')
            record_source("osm_basins", title="OpenStreetMap basins", url=OVERPASS[0], licence="ODbL 1.0, (c) OpenStreetMap contributors",
                          path=RAW / "osm_basins.json", note="Checked for mapped debris or detention basins inside the map window.")
            for el in els:
                lon, lat = (el["lon"], el["lat"]) if "lon" in el else (el["center"]["lon"], el["center"]["lat"])
                x, y = to_utm.transform(lon, lat)
                r0, c0 = cell(x, y)
                if zone_dist[r0, c0] <= 300:          # only basins a mud path could fill
                    basins.append({"x": x, "y": y, "name": el.get("tags", {}).get("name"), "ha": float(up_ha[r0, c0]), "k": int(zone_first[r0, c0])})
        except Exception as ex:
            print("basin lookup skipped:", ex)
            basins = None

    rows = [{"kind": "crossing", "road": name_of[q["wi"]] or "Unnamed road", "hw": str(hw_of[q["wi"]]), "ha": round(q["ha"], 1), "k": q["k"], "on_route": int(q["on_route"]),
             "geometry": Point(q["x"], q["y"])} for q in points]
    rows += [{"kind": "basin", "road": b["name"] or "Mapped basin", "hw": "", "ha": round(b["ha"], 1), "k": b["k"] if b["k"] != NEVER else 0, "on_route": 0,
              "geometry": Point(b["x"], b["y"])} for b in (basins or [])]
    rows.sort(key=lambda q: (-q["on_route"], -q["ha"]))
    for i, q in enumerate(rows):
        q["rank"] = i + 1
    clear_gdf = gpd.GeoDataFrame(rows, crs=crs) if rows else gpd.GeoDataFrame({"kind": [], "road": [], "hw": [], "ha": [], "k": [], "on_route": [], "rank": []}, geometry=[], crs=crs)
    clear_gdf.to_file(WORK / "clear_points.geojson", driver="GeoJSON")

    out = {
        "rule": {"zone_cost": ZONE_COST, "clear_m": CLEAR_M, "cluster_m": CLUSTER_M, "ends_on": tier},
        "routes": summary, "blocks": block_route, "homes_routed": int(sum(r["homes"] for r in summary)), "homes_without_route": no_route,
        "clear_points": len(rows), "clear_points_on_route": int(sum(q["on_route"] for q in rows)),
        "osm_basins_checked": basins is not None, "osm_basins_found": len(basins or []),
    }
    (WORK / "routes.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "blocks"}, indent=1))
    for q in rows[:12]:
        print({k: v for k, v in q.items() if k != "geometry"})


if __name__ == "__main__":
    main()
