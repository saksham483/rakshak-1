#!/usr/bin/env bash
# Downloads the real NASA SMAP/MSL spacecraft telemetry anomaly dataset
# (Hundman et al. 2018, JPL - the "Telemanom" benchmark). ~250MB.
set -e
cd "$(dirname "$0")/../data/smap_msl"

echo "Fetching telemetry archive (~250MB)..."
curl -L -o data.zip https://s3-us-west-2.amazonaws.com/telemanom/data.zip
unzip -o data.zip
rm data.zip
# The zip extracts into a nested data/ dir - flatten it
if [ -d "data" ]; then
  mv data/* .
  rmdir data
fi

echo "Fetching ground-truth labels..."
curl -L -o labeled_anomalies.csv https://raw.githubusercontent.com/khundman/telemanom/master/labeled_anomalies.csv

echo "Done. Test channels are under data/smap_msl/test/*.npy"
echo "Try: curl 'http://localhost:8000/api/replay/benchmark?limit_channels=5'"
