"""Immunisation indicators per district and month."""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """Add coverage, dropout and estimated zero-dose children (rolling 12 months)."""
    df = df.sort_values(["district_code", "period"]).copy()
    g = df.groupby("district_code")
    df["penta1_cov"] = df["penta1"] / df["target_under1"]
    df["dropout_p1_p3"] = np.where(df["penta1"] > 0, 1 - df["penta3"] / df["penta1"], np.nan)
    # zero-dose children accumulated over the last 12 months = target - Penta1 doses (floored at 0)
    df["zero_dose_month"] = (df["target_under1"] - df["penta1"]).clip(lower=0)
    df["zero_dose_12m"] = g["zero_dose_month"].transform(lambda s: s.rolling(12, min_periods=6).sum())
    df["penta1_cov_3m"] = g["penta1_cov"].transform(lambda s: s.rolling(3, min_periods=1).mean())
    # baseline = same district, the 12 months ending 3 months earlier
    df["baseline_cov"] = g["penta1_cov"].transform(lambda s: s.shift(3).rolling(12, min_periods=6).mean())
    df["baseline_sd"] = g["penta1_cov"].transform(lambda s: s.shift(3).rolling(12, min_periods=6).std())
    return df
