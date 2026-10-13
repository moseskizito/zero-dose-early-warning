"""End-to-end pipeline: simulate -> indicators -> warnings -> CAP alerts -> maps and GeoJSON.

Usage:  python run_pipeline.py [--period 2026-08]
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from zerodose import cap
from zerodose.indicators import compute
from zerodose.simulate import simulate
from zerodose.warning import CAP_MAP, classify, evaluate

ROOT = Path(__file__).parent
OUT = ROOT / "outputs"
COLORS = {"NORMAL": "#E8EEF4", "WATCH": "#F6D55C", "WARNING": "#ED8B39", "ALERT": "#C0392B"}

ap = argparse.ArgumentParser()
ap.add_argument("--period", default=None, help="reporting month to issue warnings for (default: latest)")
args = ap.parse_args()

districts = gpd.read_file(ROOT / "data/uganda_districts.geojson")
raw, shocks = simulate(districts.drop(columns="geometry"))
raw.to_csv(OUT / "immunisation_monthly_simulated.csv", index=False)
shocks.to_csv(OUT / "injected_shocks.csv", index=False)

hist = classify(compute(raw))
period = args.period or hist.period.max()
cur = hist[hist.period == period]
print(f"Reporting month {period}: " + ", ".join(f"{l} {int((cur.level == l).sum())}" for l in ["ALERT", "WARNING", "WATCH", "NORMAL"]))
print("Detection check against injected shocks:", evaluate(cur, shocks, hist))

# ---- GeoJSON for QGIS / GeoServer
g = districts.merge(cur[["district_code", "penta1_cov_3m", "dropout_p1_p3", "zero_dose_12m", "cusum", "level", "reason"]],
                    on="district_code")
g.to_file(OUT / f"zero_dose_risk_{period}.geojson", driver="GeoJSON")

# ---- CAP alerts for WARNING and ALERT districts, plus an Update and a Cancel to show the lifecycle
sent = dt.datetime(int(period[:4]), int(period[5:7]), 15, 9, 0, tzinfo=dt.timezone.utc)
issued = {}
for _, r in g[g.level.isin(["WARNING", "ALERT"])].sort_values("zero_dose_12m", ascending=False).iterrows():
    urg, sev, cer, resp = CAP_MAP[r.level]
    a = cap.build_alert(
        sender="situationroom@opm.go.ug.example", event="Zero-dose children risk", category="Health",
        urgency=urg, severity=sev, certainty=cer, response_type=resp, sent=sent,
        headline=f"{r.level}: immunisation coverage falling in {r.district} District",
        description=(f"Three-month Penta1 coverage is {r.penta1_cov_3m:.0%}; about {int(r.zero_dose_12m):,} children "
                     f"in the last 12 months have received no Penta1 dose. Trigger: {r.reason}. SIMULATED DATA - EXERCISE."),
        instruction="District Health Team to verify vaccine stock and session reports, and plan catch-up outreach for unreached parishes.",
        area_desc=f"{r.district} District, {r.region} Region, Uganda", polygon=cap.polygon_string(r.geometry),
        geocode=("UG-DISTRICT", r.district_code))
    problems = cap.validate(a)
    assert not problems, (r.district, problems)
    (OUT / "cap_alerts" / f"{r.district_code}_{r.district}_{period}.xml").write_bytes(cap.to_xml(a))
    issued[r.district_code] = a
if issued:
    first_code, first = next(iter(issued.items()))
    upd = cap.build_alert(sender="situationroom@opm.go.ug.example", event="Zero-dose children risk", category="Health",
                          urgency="Immediate", severity="Severe", certainty="Observed", response_type="Execute",
                          msg_type="Update", references=[cap.reference_of(first)], sent=sent + dt.timedelta(days=7),
                          headline="UPDATE: catch-up campaign launched", description="Supersedes earlier alert. SIMULATED - EXERCISE.",
                          instruction="Continue daily reporting of catch-up doses.",
                          area_desc=first.findtext(f".//{{{cap.NS}}}areaDesc"),
                          polygon=first.findtext(f".//{{{cap.NS}}}polygon"), geocode=("UG-DISTRICT", first_code))
    cancel = cap.build_alert(sender="situationroom@opm.go.ug.example", event="Zero-dose children risk", category="Health",
                             urgency="Past", severity="Minor", certainty="Observed", response_type="AllClear",
                             msg_type="Cancel", references=[cap.reference_of(upd)], sent=sent + dt.timedelta(days=45),
                             headline="CANCEL: coverage restored", description="Coverage back above 90%. SIMULATED - EXERCISE.",
                             instruction="Resume routine monitoring.",
                             area_desc=first.findtext(f".//{{{cap.NS}}}areaDesc"),
                             polygon=first.findtext(f".//{{{cap.NS}}}polygon"), geocode=("UG-DISTRICT", first_code))
    for name, m in [("lifecycle_2_update", upd), ("lifecycle_3_cancel", cancel)]:
        assert not cap.validate(m), cap.validate(m)
        (OUT / "cap_alerts" / f"{name}.xml").write_bytes(cap.to_xml(m))
print(f"CAP messages written: {len(issued)} alerts + update + cancel (all validated)")

# ---- map
fig, axes = plt.subplots(1, 2, figsize=(12, 6.2))
g.plot(ax=axes[0], color=g.level.map(COLORS), edgecolor="white", linewidth=0.4)
axes[0].legend(handles=[Patch(color=COLORS[l], label=l.title()) for l in ["ALERT", "WARNING", "WATCH", "NORMAL"]],
               loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=4, frameon=False, fontsize=9)
axes[0].set_title(f"Zero-dose risk level, {period}")
g.plot(ax=axes[1], column="zero_dose_12m", cmap="Reds", edgecolor="white", linewidth=0.4, legend=True,
       legend_kwds={"label": "zero-dose children, last 12 months", "shrink": 0.7})
axes[1].set_title("Estimated zero-dose children (12-month total)")
for ax in axes:
    ax.set_axis_off()
fig.suptitle("Uganda districts — SIMULATED immunisation data (demonstration)", fontsize=10, color="#555")
fig.tight_layout()
fig.savefig(OUT / "zero_dose_map.png", dpi=150)

# ---- trend chart for the most severe district
top = g.sort_values(["level", "cusum"], ascending=[True, False])
top = g[g.level == "ALERT"].sort_values("cusum", ascending=False) if (g.level == "ALERT").any() else g.sort_values("cusum", ascending=False)
code = top.iloc[0].district_code
s = hist[hist.district_code == code]
fig, ax = plt.subplots(figsize=(9, 3.4))
ax.plot(s.period, s.penta1_cov * 100, color="#555", lw=1.2, label="monthly Penta1 coverage")
ax.plot(s.period, s.penta1_cov_3m * 100, color="#2E86C1", lw=2, label="3-month average")
for lvl in ["WARNING", "ALERT"]:
    m = s[s.level == lvl]
    ax.scatter(m.period, m.penta1_cov_3m * 100, s=28, color=COLORS[lvl], zorder=3, label=lvl.title())
ax.axhline(90, ls="--", lw=0.8, color="#999"); ax.axhline(80, ls=":", lw=0.8, color="#999")
ax.set_xticks(s.period[::6]); ax.tick_params(axis="x", labelrotation=45, labelsize=8)
ax.set_ylabel("coverage (%)")
ax.set_title(f"{top.iloc[0].district} District — Penta1 coverage and warnings (simulated)")
ax.legend(frameon=False, fontsize=8, ncol=4, loc="lower left")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(OUT / "district_trend.png", dpi=150)
print("Outputs in", OUT)
