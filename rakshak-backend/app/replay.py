"""
Validates the live detection engine against NASA's real, expert-labeled spacecraft
anomaly dataset (Hundman et al. 2018, JPL - the SMAP/MSL "Telemanom" benchmark).

The dataset itself (~250MB of real telemetry .npy files) is too large to bundle here and
isn't reachable from a sandboxed build environment; run scripts/download_dataset.sh once
on a machine with normal internet access to fetch it locally. Everything in this module
degrades gracefully (returns a clear "not found" message) until that's done.

Being upfront: this scores our lightweight EWMA detector, not the original LSTM. The point
isn't to beat the published benchmark - it's an honest, reproducible check against real
labeled spacecraft anomalies rather than only our own synthetic scenarios.
"""
import os
import csv
import ast

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "smap_msl")
LABELS_PATH = os.path.join(DATA_DIR, "labeled_anomalies.csv")
TEST_DIR = os.path.join(DATA_DIR, "test")

NOT_FOUND_MSG = (
    "NASA SMAP/MSL dataset not found locally. Run scripts/download_dataset.sh "
    "(fetches ~250MB from the original sources) then retry."
)


def _load_labels():
    if not os.path.exists(LABELS_PATH):
        return None
    rows = []
    with open(LABELS_PATH) as f:
        for row in csv.DictReader(f):
            row["anomaly_sequences"] = ast.literal_eval(row["anomaly_sequences"])
            rows.append(row)
    return rows


def list_available_channels():
    labels = _load_labels()
    if labels is None:
        return {"available": False, "message": NOT_FOUND_MSG, "channels": []}
    present = [r["chan_id"] for r in labels if os.path.exists(os.path.join(TEST_DIR, r["chan_id"] + ".npy"))]
    return {"available": len(present) > 0, "channels": present, "total_labeled_channels": len(labels)}


def run_benchmark(channel: str = None, limit_channels: int = 5):
    labels = _load_labels()
    if labels is None:
        return {"available": False, "message": NOT_FOUND_MSG}

    try:
        import numpy as np
    except ImportError:
        return {"available": False, "message": "numpy not installed."}

    from .detection import Detector

    targets = [r for r in labels if channel is None or r["chan_id"] == channel][:limit_channels]
    results = []
    for row in targets:
        path = os.path.join(TEST_DIR, row["chan_id"] + ".npy")
        if not os.path.exists(path):
            continue
        data = np.load(path)
        series = data[:, 0] if data.ndim > 1 else data
        n = len(series)
        true_mask = np.zeros(n, dtype=bool)
        for seq in row["anomaly_sequences"]:
            s, e = seq
            true_mask[s:min(e, n)] = True

        warm = series[:50]
        det = Detector(base_mean=float(warm.mean()), base_var=float(warm.var() + 1e-6))
        pred_mask = np.zeros(n, dtype=bool)
        for i in range(n):
            det.update(float(series[i]))
            pred_mask[i] = det.status == "anomaly"

        tp = int(np.sum(pred_mask & true_mask))
        fp = int(np.sum(pred_mask & ~true_mask))
        fn = int(np.sum(~pred_mask & true_mask))
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        results.append({
            "channel": row["chan_id"], "spacecraft": row["spacecraft"], "n_points": n,
            "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3),
        })

    if not results:
        return {"available": False, "message": "No matching .npy files found for the requested channel(s)."}

    avg_f1 = round(sum(r["f1"] for r in results) / len(results), 3)
    return {
        "available": True, "results": results, "avg_f1": avg_f1,
        "note": ("Same lightweight EWMA/z-score engine used for live monitoring, run point-by-point "
                 "over real labeled NASA telemetry. This is an honest baseline comparison against real "
                 "data, not a claim of beating the published Telemanom LSTM benchmark."),
    }
