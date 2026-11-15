"""Step 2b: is NASA's own radar disturbance alert available for this fire yet?

OPERA DIST-ALERT-S1 is the finished radar product built for exactly this job.
It was released on 27 October 2026 and its archive is still being filled in.
This step asks the archive what it holds over the study window and writes the
answer down, so the site can say plainly which radar source drew the scar.

When the archive reaches the fire's dates, the scar should be read from the
product's own confirmed-alert layers instead of step 3.

Needs a free NASA Earthdata login in ~/.netrc (never committed).
"""
import json
import re

import earthaccess

from common import record_source
from config import WORK

SHORT_NAME = "OPERA_L3_DIST-ALERT-S1_V1"


def main():
    fire = json.loads((WORK / "fire.json").read_text())
    start = fire["usgs"]["start_date"]
    earthaccess.login(strategy="netrc")
    res = earthaccess.search_data(short_name=SHORT_NAME, bounding_box=tuple(fire["bbox"]), count=5000)
    dates = sorted({re.search(r"_T\w{5}_(\d{8})T", g["umm"]["GranuleUR"]).group(1) for g in res})
    iso = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates]
    after = [d for d in iso if d >= start]
    out = {"product": SHORT_NAME, "granules_over_window": len(res), "first_date": iso[0] if iso else None, "last_date": iso[-1] if iso else None,
           "dates_after_ignition": len(after), "available_for_fire": bool(after)}
    (WORK / "dist.json").write_text(json.dumps(out, indent=1))
    record_source(
        "opera_dist_alert_s1", title="NASA OPERA L3 DIST-ALERT-S1 v1 availability check", url="https://search.asf.alaska.edu/#/?dataset=OPERA-S1&productTypes=DIST-ALERT-S1",
        licence="NASA open data (CC0)", path=None, status="ok" if after else "not yet available for this fire",
        note=f"{len(res)} granules over the study window, acquired {out['first_date']} to {out['last_date']}; {len(after)} acquisition dates on or after ignition ({start}). "
             "Until the archive reaches the fire, the scar is drawn from OPERA RTC-S1, the backscatter product DIST-ALERT-S1 is itself made from.",
    )
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
