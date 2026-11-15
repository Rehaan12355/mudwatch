"""Step 5: who lives below?

Three public sources, joined so that people sit where the houses are:
- 2020 Census blocks with their population (the smallest census unit)
- building outlines from the FEMA / Oak Ridge "USA Structures" inventory
- OpenStreetMap road and place names, used only for labels and road counts

A block's census population is shared equally among the homes mapped inside
it. That puts people on the valley floors where the houses are, instead of
smearing them across a whole block of forest. "Homes" are the largest
residential buildings in each block, as many as the census counts housing units.
"""
import json
import time

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import LineString, Point, box

from common import UA, fetch, record_source
from config import FIRE, RAW, WORK

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/12/query"
STRUCT = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/USA_Structures_View/FeatureServer/0/query"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass-api.de/api/interpreter"]


def paged(url, name, params, page):
    frames, offset = [], 0
    while True:
        path = fetch(url, f"{name}_{offset}.json", params=dict(params, resultOffset=offset, resultRecordCount=page), timeout=300)
        d = json.loads(path.read_text())
        if "features" not in d:
            path.unlink()
            raise RuntimeError(f"{name}: {str(d)[:200]}")
        frames.append(d["features"])
        if len(d["features"]) < page and not d.get("exceededTransferLimit") and not d.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(d["features"])
    return [f for fr in frames for f in fr]


def overpass(name, query):
    path = RAW / name
    if not path.exists():
        last = None
        for url in OVERPASS:
            try:
                r = requests.post(url, data={"data": query}, headers=UA, timeout=180)
                r.raise_for_status()
                json.loads(r.content)["elements"]
                path.write_bytes(r.content)
                break
            except Exception as e:
                last = e
                time.sleep(5)
        else:
            raise RuntimeError(f"OpenStreetMap service unavailable: {last}")
    return json.loads(path.read_text())["elements"]


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    w, s, e, n = fire["bbox"]
    env = f"{w},{s},{e},{n}"

    # --- census blocks ----------------------------------------------------------
    feats = paged(TIGER, "blocks", {"geometry": env, "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
                                    "where": "1=1", "outFields": "GEOID,POP100,HU100", "outSR": 4326, "orderByFields": "GEOID", "f": "geojson"}, 1000)
    blocks = gpd.GeoDataFrame.from_features(feats, crs=4326).drop_duplicates("GEOID").reset_index(drop=True)
    blocks["pop"] = blocks["POP100"].astype(int)
    blocks["units"] = blocks["HU100"].astype(int)
    record_source("census_blocks", title="2020 Census blocks with population and housing units", url=TIGER, licence="US Government work, public domain",
                  path=None, note=f"TIGERweb layer 'Census 2020 > Census Blocks', fields POP100 and HU100, every block touching the study window ({len(blocks)} blocks).")

    # --- buildings --------------------------------------------------------------
    bw, bs, be, bn = blocks.total_bounds   # blocks reach past the window; fetch their buildings too so shares are right
    rows = paged(STRUCT, "structures", {"geometry": f"{bw},{bs},{be},{bn}", "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                                        "where": "1=1", "outFields": "BUILD_ID,OCC_CLS,PRIM_OCC,OUTBLDG,SQMETERS,LONGITUDE,LATITUDE",
                                        "returnGeometry": "false", "orderByFields": "OBJECTID", "f": "json"}, 2000)
    st = pd.DataFrame([r["attributes"] for r in rows]).drop_duplicates("BUILD_ID")
    st = gpd.GeoDataFrame(st, geometry=gpd.points_from_xy(st["LONGITUDE"], st["LATITUDE"]), crs=4326)
    record_source("usa_structures", title="USA Structures building inventory (FEMA and Oak Ridge National Laboratory)", url=STRUCT.rsplit("/", 1)[0],
                  licence="Public domain (US Government work)", path=None,
                  note=f"{len(st)} buildings in and around the study window; occupancy class and centre point used.")
    st = gpd.sjoin(st, blocks[["GEOID", "geometry"]], how="left", predicate="within").drop(columns="index_right").rename(columns={"GEOID": "block"})
    # The inventory files garages, barns and workshops on a house lot as "Residential" too. The census says how many
    # housing units each block has, so in every block that many of the largest residential buildings are taken as the homes.
    res = st[(st["OCC_CLS"] == "Residential") & st["block"].notna()].sort_values("SQMETERS", ascending=False)
    rank = res.groupby("block").cumcount()
    units = res["block"].map(blocks.set_index("GEOID")["units"])
    st["home"] = False
    st.loc[res.index[(rank < units).values], "home"] = True
    n_homes = st[st["home"]].groupby("block").size()
    blocks["homes"] = blocks["GEOID"].map(n_homes).fillna(0).astype(int)
    per_home = (blocks.set_index("GEOID")["pop"] / blocks.set_index("GEOID")["homes"].where(blocks.set_index("GEOID")["homes"] > 0))
    st["people"] = st["block"].map(per_home).where(st["home"], 0.0).fillna(0.0)
    placed = float(st["people"].sum())
    unplaced = int(blocks.loc[blocks["homes"] == 0, "pop"].sum())

    # --- names and roads --------------------------------------------------------
    try:
        els = overpass("osm_places.json", f'[out:json][timeout:90];(node["place"~"city|town|village|hamlet|locality|neighbourhood"]["name"]({bs},{bw},{bn},{be}););out;')
        places = gpd.GeoDataFrame({"pname": [x["tags"]["name"] for x in els], "kind": [x["tags"]["place"] for x in els]},
                                  geometry=[Point(x["lon"], x["lat"]) for x in els], crs=4326)
        els = overpass("osm_roads.json", f'[out:json][timeout:120];(way["highway"~"motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track"]({s},{w},{n},{e}););out geom;')
        roads = gpd.GeoDataFrame({"name": [x.get("tags", {}).get("name") for x in els], "highway": [x["tags"]["highway"] for x in els]},
                                 geometry=[LineString([(p["lon"], p["lat"]) for p in x["geometry"]]) for x in els], crs=4326)
        record_source("osm", title="OpenStreetMap roads and place names", url=OVERPASS[0], licence="ODbL 1.0, (c) OpenStreetMap contributors",
                      path=RAW / "osm_roads.json", note="Used to label blocks with a road and a nearby place, and to measure road length inside mud paths.")
    except Exception as ex:   # names are a nicety; block numbers still work
        print("OpenStreetMap unavailable:", ex)
        places = gpd.GeoDataFrame({"pname": [], "kind": []}, geometry=[], crs=4326)
        roads = gpd.GeoDataFrame({"name": [], "highway": []}, geometry=[], crs=4326)

    utm = FIRE["utm_epsg"]
    bu = blocks.to_crs(utm)
    # Label: the named road with the most length inside the block, and the nearest settlement.
    blocks["road"] = None
    named = roads[roads["name"].notna() & roads["highway"].isin(["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential"])].to_crs(utm)
    if len(named):
        cut = gpd.overlay(named[["name", "geometry"]], bu[["GEOID", "geometry"]].assign(geometry=bu.buffer(15)), how="intersection", keep_geom_type=True)
        cut["len"] = cut.length
        best = cut.groupby(["GEOID", "name"])["len"].sum().reset_index().sort_values("len").drop_duplicates("GEOID", keep="last").set_index("GEOID")
        blocks["road"] = blocks["GEOID"].map(best["name"][best["len"] >= 60])
    blocks["place"], blocks["place_km"] = None, None
    towns = places[places["kind"].isin(["city", "town", "village", "hamlet"])].to_crs(utm)
    if len(towns):
        pts = bu.assign(geometry=bu.representative_point())[["GEOID", "geometry"]]
        near = gpd.sjoin_nearest(pts, towns, distance_col="d").sort_values("d").drop_duplicates("GEOID").set_index("GEOID")
        blocks["place"] = blocks["GEOID"].map(near["pname"])
        blocks["place_km"] = blocks["GEOID"].map((near["d"] / 1000).round(1))

    blocks[["GEOID", "pop", "units", "homes", "road", "place", "place_km", "geometry"]].to_file(WORK / "blocks.gpkg", driver="GPKG")
    st[["BUILD_ID", "OCC_CLS", "PRIM_OCC", "home", "block", "people", "SQMETERS", "geometry"]].to_file(WORK / "structures.gpkg", driver="GPKG")
    roads.to_file(WORK / "roads.gpkg", driver="GPKG")
    inwin = st[st.within(box(w, s, e, n))]
    summary = {"blocks": len(blocks), "populated_blocks": int((blocks["pop"] > 0).sum()), "block_population": int(blocks["pop"].sum()),
               "buildings": len(st), "homes": int(st["home"].sum()), "homes_in_window": int(inwin["home"].sum()),
               "people_placed_on_homes": round(placed), "people_in_blocks_without_mapped_homes": unplaced,
               "people_in_window": round(float(inwin["people"].sum()))}
    (WORK / "people.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    print(blocks[blocks["pop"] > 0][["GEOID", "pop", "homes", "road", "place", "place_km"]].sample(12, random_state=1).to_string())


if __name__ == "__main__":
    main()
