#!/bin/sh
# Build one fire end to end: MW_FIRE=<id> sh run_all.sh   (fires are defined in config.py)
set -e
cd "$(dirname "$0")"
for s in s01_fire s02_radar s02b_dist s03_scar s04_slope s05_people s06_zones s06b_routes s07_usgs s08_nisar s09_optical s10_build; do
  echo "== $s"
  ../.venv/bin/python $s.py
done
