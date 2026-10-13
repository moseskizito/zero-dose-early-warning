"""Simulate monthly district immunisation reports (DHIS2/HMIS 105-style aggregates).

Real district names and boundaries (Natural Earth) are used; all numbers are SIMULATED.
A "zero-dose" child is one who has not received the first dose of DPT-containing
vaccine (Penta1) by age one, following the Gavi/WHO definition.

Some districts are given a deterioration from a set month (stock-out, insecurity,
health-worker strike, outbreak disruption) so the warning system can be tested.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SHOCKS = ["vaccine stock-out", "insecurity / displacement", "health-worker strike", "outreach suspended"]


def simulate(districts: pd.DataFrame, start="2023-01", months=44, seed=21, shock_share=0.12):
    rng = np.random.default_rng(seed)
    periods = pd.period_range(start, periods=months, freq="M")
    rows, shocks = [], []
    for _, d in districts.iterrows():
        births_year = rng.lognormal(np.log(14000), 0.55)  # surviving infants per year
        base_cov = np.clip(rng.normal(0.93, 0.06), 0.65, 1.05)  # Penta1 coverage
        if d["region"] in ("Northern",):
            base_cov -= rng.uniform(0.0, 0.08)
        drop = np.clip(rng.normal(0.06, 0.03), 0.0, 0.2)  # Penta1 -> Penta3 dropout
        shock_start, shock_kind, depth = None, None, 0.0
        if rng.random() < shock_share:
            shock_start = int(rng.integers(24, months - 4))
            shock_kind = rng.choice(SHOCKS)
            depth = rng.uniform(0.25, 0.55)
            shocks.append(dict(district_code=d["district_code"], district=d["district"],
                               shock_start=str(periods[shock_start]), shock=shock_kind, depth=round(depth, 2)))
        for i, p in enumerate(periods):
            target = births_year / 12
            season = 1 - 0.05 * np.cos(2 * np.pi * (p.month - 1) / 12)  # dip around January holidays
            cov = base_cov * season
            if shock_start is not None and i >= shock_start:
                ramp = min(1.0, (i - shock_start + 1) / 3)
                cov *= 1 - depth * ramp
            penta1 = rng.poisson(max(target * cov, 0))
            penta3 = rng.binomial(penta1, 1 - drop) if penta1 else 0
            mcv1 = rng.binomial(penta3, np.clip(rng.normal(0.92, 0.03), 0.7, 1.0)) if penta3 else 0
            rows.append(dict(district_code=d["district_code"], district=d["district"], region=d["region"],
                             period=str(p), target_under1=round(target), penta1=penta1, penta3=penta3, mcv1=mcv1))
    return pd.DataFrame(rows), pd.DataFrame(shocks)
