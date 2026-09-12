"""可移植、无 pickle 的有限元结果存档。"""
from pathlib import Path
from dataclasses import fields
import hashlib
import json
import os
import numpy as np
from .models import SimulationConfig, SimulationResult

ARRAY_FIELDS = ("points_mm", "cell_stress_axial_mpa", "cell_eq_plastic_strain", "cell_damage", "cell_active")
FORMAT_VERSION = 2

def plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value

def save_result(result, filename):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    optional = {key for f in result.frames for key, value in f.items()
                if isinstance(value, np.ndarray) and key not in ("initial_points", "cells")}
    array_keys = sorted(set(ARRAY_FIELDS) | optional)
    array_keys = [key for key in array_keys if all(key in f for f in result.frames)]
    excluded = set(array_keys) | {"initial_points", "cells"}
    meta = {"format_version": FORMAT_VERSION, "config": result.config.to_dict(),
            "summary": plain(result.summary), "diagnostics": plain(result.diagnostics), "array_fields": array_keys,
            "frames": [{k: plain(v) for k, v in f.items() if k not in excluded} for f in result.frames]}
    arrays = {"initial_points": result.initial_points, "cells": result.cells,
              "metadata_json": np.asarray(json.dumps(meta, ensure_ascii=False))}
    for key in array_keys:
        if result.frames:
            arrays[key] = np.stack([np.asarray(f[key]) for f in result.frames])
    temporary = filename.with_suffix(filename.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    temporary.replace(filename)
    return str(filename)

def load_result(filename):
    with np.load(filename, allow_pickle=False) as data:
        meta = json.loads(str(data["metadata_json"]))
        if meta.get("format_version") not in (1, FORMAT_VERSION):
            raise ValueError("结果文件版本不受支持")
        valid = {f.name for f in fields(SimulationConfig)}
        config = SimulationConfig(**{k: v for k, v in meta["config"].items() if k in valid})
        initial = data["initial_points"].copy()
        cells = data["cells"].copy()
        frames = []
        for i, frame in enumerate(meta["frames"]):
            for key in meta.get("array_fields", ARRAY_FIELDS):
                frame[key] = data[key][i].copy()
            frame["initial_points"] = initial
            frame["cells"] = cells
            frames.append(frame)
        from .engine import decorate
        return decorate(SimulationResult(config, initial, cells, frames, meta["summary"], meta["diagnostics"]))

def cache_path(config):
    body = json.dumps(config.to_dict(), sort_keys=True).encode("utf-8")
    import os
    backend = os.environ.get('MECHANICS_BACKEND', 'auto').encode('ascii')
    fingerprint = hashlib.sha256(b"mechanics-six-v2.1-abi1:" + backend + body).hexdigest()[:24]
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MechanicsVirtualLab" / "cache"
    return base / (fingerprint + ".npz")
