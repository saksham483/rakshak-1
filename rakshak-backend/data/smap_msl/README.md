Run `../../scripts/download_dataset.sh` from this directory's parent script location
(i.e. `bash scripts/download_dataset.sh` from the project root) to populate this folder
with the real NASA SMAP/MSL telemetry anomaly dataset. Until then, `/api/replay/*`
endpoints will report the dataset as unavailable rather than failing silently.
