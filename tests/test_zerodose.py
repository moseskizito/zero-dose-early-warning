from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import geopandas as gpd
from zerodose import cap
from zerodose.indicators import compute
from zerodose.simulate import simulate
from zerodose.warning import classify

D = gpd.read_file(Path(__file__).resolve().parents[1] / "data/uganda_districts.geojson")
raw, shocks = simulate(D.drop(columns="geometry").head(30), seed=3, shock_share=0.3)
hist = classify(compute(raw))


def test_districts_are_real_uganda_boundaries():
    assert len(D) == 112 and D.geometry.is_valid.all()
    b = D.total_bounds
    assert 29 < b[0] < 31 and 34 < b[2] < 36 and -2 < b[1] < 0 and 3 < b[3] < 5


def test_dose3_never_exceeds_dose1():
    assert (raw.penta3 <= raw.penta1).all()


def test_shocked_districts_reach_warning():
    for _, s in shocks.iterrows():
        h = hist[(hist.district_code == s.district_code) & (hist.period >= s.shock_start)]
        assert h.level.isin(["WARNING", "ALERT"]).any(), s.district


def test_cap_message_valid_and_lifecycle():
    geom = D.geometry.iloc[0]
    a = cap.build_alert(sender="x@y", event="t", category="Health", urgency="Expected", severity="Moderate",
                        certainty="Likely", headline="h", description="d", instruction="i", area_desc="a",
                        polygon=cap.polygon_string(geom), geocode=("UG-DISTRICT", "UG-D001"))
    assert cap.validate(a) == []
    bad = cap.build_alert(sender="x@y", event="t", category="Health", urgency="Expected", severity="Moderate",
                          certainty="Likely", headline="h", description="d", instruction="i", area_desc="a",
                          polygon=cap.polygon_string(geom), geocode=("UG-DISTRICT", "UG-D001"), msg_type="Cancel")
    assert "Update/Cancel must carry <references>" in cap.validate(bad)
