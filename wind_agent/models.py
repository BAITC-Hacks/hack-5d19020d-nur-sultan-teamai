"""CPU models trained only on archived NWP inputs; no measured wind at forecast time."""
import uuid

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor

from .config import data_root, iso, now, project, utc
from .features import FEATURES, features
from .storage import read_json, sha256, write_json

CANDIDATES = ["train_mean", "wind_bins", "catboost_small", "catboost_medium", "catboost_pooled"]


def _cat(kind, quantiles=False):
    return CatBoostRegressor(iterations=250 if kind == "catboost_small" else 400,
                            depth=4 if kind == "catboost_small" else 6, learning_rate=.045,
                            loss_function="MultiQuantile:alpha=0.1,0.5,0.9" if quantiles else "RMSE",
                            random_seed=42, thread_count=2, l2_leaf_reg=8, verbose=False,
                            allow_writing_files=False)


class PowerModel:
    def __init__(self, kind="catboost_small"):
        if kind not in CANDIDATES:
            raise ValueError("Unregistered model")
        self.kind = kind
        self.models = {}
        self.quantiles = {}
        self.baselines = {}
        self.card = {}

    def fit(self, frame, cutoff, with_intervals=False):
        cutoff = utc(cutoff)
        if frame.empty or (frame.obs_available_at > cutoff).any() or (frame.origin >= cutoff).any():
            raise ValueError("Empty training frame or information after training cutoff")
        for site_id, group in frame.groupby("site_id"):
            if len(group) < 300:
                raise ValueError(f"Too few training rows for {site_id}: {len(group)} (<300)")
            bins = np.minimum((group.wind100 / 1.5).astype(int), 30)
            curve = group.groupby(bins).power.mean()
            self.baselines[site_id] = {"mean": float(group.power.mean()),
                                       "bins": {str(k): float(v) for k, v in curve.items()}}
        if self.kind.startswith("catboost"):
            groups = [("pooled", frame)] if self.kind == "catboost_pooled" else list(frame.groupby("site_id"))
            for key, group in groups:
                x = features(group)
                categorical = []
                if key == "pooled":
                    x["site_id"] = group.site_id.to_numpy()
                    categorical = ["site_id"]
                model = _cat(self.kind)
                model.fit(x, group.power, sample_weight=group.sample_weight, cat_features=categorical)
                self.models[key] = model
                if with_intervals:
                    qm = _cat(self.kind, quantiles=True)
                    qm.fit(x, group.power, sample_weight=group.sample_weight, cat_features=categorical)
                    self.quantiles[key] = qm
        self.card = {"kind": self.kind, "created_at": iso(now()), "fit_cutoff": iso(cutoff),
                     "max_observation_available_at": iso(frame.obs_available_at.max()),
                     "train_rows": len(frame), "unique_target_hours": int(frame.groupby(["site_id", "target_time"]).ngroups),
                     "first_target": iso(frame.target_time.min()), "last_target": iso(frame.target_time.max()),
                     "config_hash": project().fingerprint, "features": FEATURES,
                     "point_estimator": "conditional_mean_squared_error", "mode": "weather_only_frozen",
                     "quantiles": bool(self.quantiles), "random_seed": 42}
        return self

    def predict(self, frame):
        result = pd.DataFrame(index=frame.index, columns=["prediction", "p10", "p50", "p90"], dtype=float)
        for site_id, group in frame.groupby("site_id"):
            if site_id not in self.baselines:
                raise ValueError("Unknown site for model")
            baseline = self.baselines[site_id]
            if self.kind == "train_mean":
                result.loc[group.index, "prediction"] = baseline["mean"]
            elif self.kind == "wind_bins":
                bins = np.minimum((group.wind100/1.5).astype(int), 30)
                xs = sorted(int(k) for k in baseline["bins"])
                ys = [baseline["bins"][str(k)] for k in xs]
                result.loc[group.index, "prediction"] = np.interp(bins, xs, ys)
            else:
                x = features(group)
                key = "pooled" if self.kind == "catboost_pooled" else site_id
                if key == "pooled":
                    x["site_id"] = group.site_id.to_numpy()
                result.loc[group.index, "prediction"] = self.models[key].predict(x)
                if key in self.quantiles:
                    q = np.sort(self.quantiles[key].predict(x), axis=1)
                    result.loc[group.index, ["p10", "p50", "p90"]] = q
        # Only predictions are bounded. Observed values are never clipped.
        return result.clip(0, 1)

    def save(self, extra=None):
        version = f"{now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        root = data_root() / "models" / version
        root.mkdir(parents=True)
        checksums = {}
        for prefix, models in [("point", self.models), ("quantile", self.quantiles)]:
            for key, model in models.items():
                path = root / f"{prefix}-{key}.cbm"
                model.save_model(str(path))
                checksums[path.name] = sha256(path)
        self.card.update(version=version, baselines=self.baselines, files=checksums, **(extra or {}))
        write_json(root / "card.json", self.card)
        return version

    @classmethod
    def load(cls, version):
        if not version or any(c not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_" for c in version):
            raise ValueError("Invalid model version")
        root = data_root() / "models" / version
        card = read_json(root / "card.json")
        if card["config_hash"] != project().fingerprint:
            raise ValueError("Model was trained under another configuration; retrain")
        model = cls(card["kind"])
        model.card, model.baselines = card, card["baselines"]
        for filename, expected in card["files"].items():
            path = root / filename
            if sha256(path) != expected:
                raise ValueError("Model artifact checksum mismatch")
            cb = CatBoostRegressor()
            cb.load_model(str(path))
            prefix, key = path.stem.split("-", 1)
            (model.models if prefix == "point" else model.quantiles)[key] = cb
        return model


def active_model():
    path = data_root() / "models" / "active.json"
    if not path.exists():
        raise FileNotFoundError("No validated model registered. Run wind-agent train")
    return PowerModel.load(read_json(path)["version"])
