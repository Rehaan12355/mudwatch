"""Step 4: how steep is the ground?

Elevation comes from NASADEM, NASA's reprocessed Shuttle Radar Topography
Mission heights (1 arc-second, about 30 m). The tiles over the study window
are placed on the analysis grid and slope is worked out for every cell from
its eight neighbours (Horn's method, the one most GIS software uses).

Needs a free NASA Earthdata login in ~/.netrc (never committed).
"""
import io
import json
import math
import zipfile

import earthaccess
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.merge import merge
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from common import record_source
from config import FIRE, RAW, STEEP_DEG, WORK

SHORT_NAME = "NASADEM_HGT"


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    shape = (g["height"], g["width"])
    tf = from_origin(g["x0"], g["y1"], g["res"], g["res"])
    w, s, e, n = fire["bbox"]
    want = {f"{'n' if la >= 0 else 's'}{abs(la):02d}{'w' if lo < 0 else 'e'}{abs(lo):03d}"
            for la in range(math.floor(s), math.floor(n) + 1) for lo in range(math.floor(w), math.floor(e) + 1)}
    earthaccess.login(strategy="netrc")
    session = earthaccess.get_requests_https_session()
    res = earthaccess.search_data(short_name=SHORT_NAME, bounding_box=(w, s, e, n), count=20)
    tiles = []
    for gran in res:
        url = next(l for l in gran.data_links() if l.endswith(".zip"))
        name = url.rsplit("/", 1)[-1]
        if not any(t in name for t in want):
            continue
        path = RAW / name
        if not path.exists():
            r = session.get(url, timeout=300)
            r.raise_for_status()
            path.write_bytes(r.content)
        with zipfile.ZipFile(path) as zf:
            hgt = next(m for m in zf.namelist() if m.endswith(".hgt"))
            (RAW / hgt).write_bytes(zf.read(hgt))
        tiles.append(RAW / hgt)
        record_source(f"nasadem_{name.split('_')[-1].split('.')[0]}", title=f"NASADEM merged DEM, 1 arc-second, tile {name}", url=url,
                      licence="NASA open data (CC0)", path=path, note="Short name NASADEM_HGT v001 at NASA LP DAAC, doi:10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001.")
    assert len(tiles) == len(want), f"expected tiles {want}, found {[t.name for t in tiles]}"
    srcs = [rasterio.open(t) for t in tiles]
    mosaic, mtf = merge(srcs)
    dem = np.full(shape, np.nan, "float32")
    reproject(mosaic[0].astype("float32"), dem, src_transform=mtf, src_crs=srcs[0].crs, dst_transform=tf, dst_crs=f"EPSG:{g['epsg']}",
              resampling=Resampling.cubic, dst_nodata=np.nan)
    # Horn slope from the eight neighbours.
    p = np.pad(dem, 1, mode="edge")
    dzdx = ((p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])) / (8 * g["res"])
    dzdy = ((p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])) / (8 * g["res"])
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy))).astype("float32")
    prof = dict(driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="float32", crs=f"EPSG:{g['epsg']}", transform=tf, nodata=np.nan, compress="deflate")
    for name, a in (("dem", dem), ("slope", slope)):
        with rasterio.open(WORK / f"{name}.tif", "w", **prof) as dst:
            dst.write(a, 1)
    print(f"elevation {np.nanmin(dem):.0f} to {np.nanmax(dem):.0f} m; slope median {np.nanmedian(slope):.1f} deg; "
          f"{(slope >= STEEP_DEG).mean():.1%} of the window is {STEEP_DEG:.0f} degrees or steeper")


if __name__ == "__main__":
    main()
