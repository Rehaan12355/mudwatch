"""Step 8: does NISAR see the scar?

NISAR is the NASA-ISRO radar this challenge is about. Its L-band signal has a
wavelength of about 24 cm, four times longer than Sentinel-1's, so it reaches
deeper into a forest canopy and reacts strongly when trunks and branches burn.

We take the Geocoded Polarimetric Covariance (GCOV) product, which is
calibrated, terrain-corrected backscatter on a map grid: a finished product.
Two passes just before ignition and the two latest passes, all on the same
track and frame, give a before picture, an after picture and their difference.

Each file is about 5 GB; only the study window of the HV layer is read,
straight from the archive.

Needs a free NASA Earthdata login in ~/.netrc (never committed).
"""
import json
import os
import re

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import earthaccess
import h5py
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry import Polygon, box

from common import record_source
from config import WORK

SHORT_NAMES = ["NISAR_L2_GCOV_V1", "NISAR_L2_GCOV_PROVISIONAL_V1"]   # validated first, provisional where that is all there is
OUT = WORK / "nisar"
OUT.mkdir(parents=True, exist_ok=True)
NAME = re.compile(r"GCOV_\d{3}_(\d{3}_[AD]_\d{3})_\w+?_(\w{4})_\w_(\d{8})T(\d{6})_")
NEVER = 255


def fetch(url, fs, bbox):
    name = url.rsplit("/", 1)[-1]
    out = OUT / (NAME.search(name).group(3) + ".npz")
    if out.exists():
        return out
    with fs.open(url, block_size=4 * 1024 * 1024, cache_type="blockcache") as f, h5py.File(f, "r") as h:
        g = h["science/LSAR/GCOV/grids/frequencyA"]
        epsg = int(g["projection"][()])
        x, y = g["xCoordinates"][:], g["yCoordinates"][:]
        w, s, e, n = bbox
        xs, ys = Transformer.from_crs(4326, epsg, always_xy=True).transform([w, e, w, e], [s, s, n, n])
        c0, c1 = np.searchsorted(x, [min(xs), max(xs)])
        r0, r1 = np.searchsorted(-y, [-max(ys), -min(ys)])
        px = float(abs(x[1] - x[0]))
        ident = h["science/LSAR/identification"]
        np.savez_compressed(out, hv=g["HVHV"][r0:r1, c0:c1], epsg=epsg, x0=float(x[c0] - px / 2), y0=float(y[r0] + px / 2), px=px,
                            granule=name.replace(".h5", ""), doi=ident["productDoi"][()].decode() if "productDoi" in ident else "",
                            frequency=float(g["centerFrequency"][()]) if "centerFrequency" in g else np.nan)
    return out


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    g = fire["grid"]
    shape = (g["height"], g["width"])
    tf = from_origin(g["x0"], g["y1"], g["res"], g["res"])
    start = fire["usgs"]["start_date"].replace("-", "")
    earthaccess.login(strategy="netrc")
    found = {}   # (track_frame, date) -> url; validated copies win over provisional ones
    cover = {}   # track_frame -> share of the study window inside the frame
    window = box(*fire["bbox"])
    for sn in reversed(SHORT_NAMES):
        for gran in earthaccess.search_data(short_name=sn, bounding_box=tuple(fire["bbox"]), count=2000):
            url = next(l for l in gran.data_links() if l.endswith(".h5"))
            m = NAME.search(url)
            found[(m.group(1), m.group(3))] = url
            pts = gran["umm"]["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"][0]["Boundary"]["Points"]
            cover[m.group(1)] = Polygon([(p["Longitude"], p["Latitude"]) for p in pts]).intersection(window).area / window.area
    # A track that covers the whole window, with passes both shortly before ignition and well after it.
    best = None
    for tfr in sorted(t for t, c in cover.items() if c > 0.99):
        dates = sorted(d for t, d in found if t == tfr)
        pre, post = [d for d in dates if d < start][-2:], [d for d in dates if d > start][-2:]
        if len(pre) == 2 and len(post) == 2 and (best is None or pre[-1] > best[1][-1]):
            best = (tfr, pre, post)
    if best is None:
        (WORK / "nisar.json").write_text(json.dumps({"ok": False, "note": "No NISAR track has two passes before and two after ignition over this fire yet."}))
        print("no usable NISAR track")
        return
    tfr, pre, post = best
    print("track/frame", tfr, "before", pre, "after", post)
    fs = earthaccess.get_fsspec_https_session()
    files = {d: fetch(found[(tfr, d)], fs, fire["bbox"]) for d in pre + post}

    def on_grid(d):
        z = np.load(files[d])
        a = np.full(shape, np.nan, "float32")
        src = z["hv"].astype("float32")
        src[~np.isfinite(src) | (src <= 0)] = np.nan
        reproject(src, a, src_transform=from_origin(float(z["x0"]), float(z["y0"]), float(z["px"]), float(z["px"])), src_crs=f"EPSG:{int(z['epsg'])}",
                  dst_transform=tf, dst_crs=f"EPSG:{g['epsg']}", resampling=Resampling.average, src_nodata=np.nan, dst_nodata=np.nan)
        return a

    with np.errstate(all="ignore"):
        before = 10 * np.log10(np.nanmean([on_grid(d) for d in pre], axis=0))
        after = 10 * np.log10(np.nanmean([on_grid(d) for d in post], axis=0))
    diff = after - before
    prof = dict(driver="GTiff", height=shape[0], width=shape[1], count=1, dtype="float32", crs=f"EPSG:{g['epsg']}", transform=tf, nodata=np.nan, compress="deflate")
    for name, a in (("nisar_before_db", before), ("nisar_after_db", after), ("nisar_change_db", diff)):
        with rasterio.open(WORK / f"{name}.tif", "w", **prof) as dst:
            dst.write(a.astype("float32"), 1)

    scar = rasterio.open(WORK / "scar_pass.tif").read(1) != NEVER
    ok = np.isfinite(diff)
    z0 = np.load(files[pre[0]])
    iso = lambda d: f"{d[:4]}-{d[4:6]}-{d[6:]}"
    out = {
        "ok": True, "product": "NISAR L2 GCOV", "band": "L", "polarization": "HV", "track_frame": tfr.replace("_", " "),
        "before_dates": [iso(d) for d in pre], "after_dates": [iso(d) for d in post],
        "posting_m": float(z0["px"]), "doi": str(z0["doi"]),
        "coverage": round(float(ok.mean()), 3),
        "change_in_scar_db": round(float(np.nanmedian(diff[scar & ok])), 2),
        "change_outside_db": round(float(np.nanmedian(diff[~scar & ok])), 2),
        # Share of the Sentinel-1 scar that NISAR also sees as clearly darker (beyond the spread of unburned ground).
        "unburned_spread_db": round(float(1.4826 * np.nanmedian(np.abs(diff[~scar & ok] - np.nanmedian(diff[~scar & ok])))), 2),
        "granules": [str(np.load(files[d])["granule"]) for d in pre + post],
    }
    thr = out["change_outside_db"] - 2 * out["unburned_spread_db"]
    out["share_of_scar_darker"] = round(float((diff[scar & ok] < thr).mean()), 3)
    out["share_of_unburned_darker"] = round(float((diff[~scar & ok] < thr).mean()), 3)
    (WORK / "nisar.json").write_text(json.dumps(out, indent=1))
    record_source(
        "nisar_gcov",
        title=f"NISAR L2 GCOV L-band backscatter, track/frame {out['track_frame']}, {', '.join(out['before_dates'] + out['after_dates'])}, study-window subset",
        url="https://search.asf.alaska.edu/#/?dataset=NISAR&productTypes=GCOV",
        licence="NASA open data (CC0); NASA-ISRO NISAR mission",
        path=None,
        note=f"Short names {', '.join(SHORT_NAMES)} at the Alaska Satellite Facility DAAC (Earthdata login). Only the study window of the HV layer was read from each ~5 GB file "
             f"({sum(f.stat().st_size for f in files.values()) / 1e6:.0f} MB kept in data/work/). Granules: " + "; ".join(out["granules"]),
    )
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
