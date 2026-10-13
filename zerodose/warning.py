"""Early-warning rules for zero-dose risk, mapped to CAP urgency/severity/certainty.

Two complementary signals per district-month:
 1. Threshold  - 3-month Penta1 coverage below programme targets (90% / 80%).
 2. Change     - one-sided CUSUM on the drop below the district's own baseline,
                 which catches a fall in a normally high-performing district.
Levels: NORMAL < WATCH < WARNING < ALERT.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LEVELS = ["NORMAL", "WATCH", "WARNING", "ALERT"]
CAP_MAP = {  # level -> (urgency, severity, certainty, responseType)
    "WATCH": ("Future", "Minor", "Possible", "Monitor"),
    "WARNING": ("Expected", "Moderate", "Likely", "Prepare"),
    "ALERT": ("Immediate", "Severe", "Observed", "Execute"),
}


def cusum_drop(z: np.ndarray, k: float = 0.5, h: float = 4.0) -> np.ndarray:
    """One-sided CUSUM on standardised shortfall (positive z = coverage below baseline)."""
    s, out = 0.0, np.zeros(len(z))
    for i, v in enumerate(np.nan_to_num(z)):
        s = max(0.0, s + v - k)
        out[i] = s
    return out


def classify(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    z = (df["baseline_cov"] - df["penta1_cov"]) / df["baseline_sd"].clip(lower=0.02)
    df["cusum"] = 0.0
    for code, idx in df.groupby("district_code").groups.items():
        df.loc[idx, "cusum"] = cusum_drop(z.loc[idx].to_numpy())
    cov = df["penta1_cov_3m"]
    level = np.select(
        [(cov < 0.70) | (df["cusum"] > 8),
         (cov < 0.80) | (df["cusum"] > 4),
         (cov < 0.90) | (df["cusum"] > 2)],
        ["ALERT", "WARNING", "WATCH"], default="NORMAL")
    df["level"] = level
    df["reason"] = np.where(df["cusum"] > 2,
                            "coverage falling below district baseline (CUSUM " + df["cusum"].round(1).astype(str) + ")",
                            "3-month Penta1 coverage " + (cov * 100).round(0).astype(int).astype(str) + "%")
    return df


def evaluate(latest_alerts: pd.DataFrame, shocks: pd.DataFrame, history: pd.DataFrame) -> dict:
    """How many simulated shocks were flagged at WARNING+ and how fast (months after onset)."""
    hits, delays = 0, []
    for _, s in shocks.iterrows():
        h = history[(history.district_code == s.district_code) & (history.period >= s.shock_start)
                    & history.level.isin(["WARNING", "ALERT"])]
        if len(h):
            hits += 1
            delays.append((pd.Period(h.period.min()) - pd.Period(s.shock_start)).n)
    quiet = history[~history.district_code.isin(shocks.district_code) & (history.period >= "2025-01")]
    return dict(shocks=len(shocks), detected=hits, median_months_to_detect=float(np.median(delays)) if delays else None,
                false_warning_rate=float(quiet.level.isin(["WARNING", "ALERT"]).mean()))
