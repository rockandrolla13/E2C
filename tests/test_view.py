"""PointInTimeView: only what was known at the decision time."""
from datetime import date, datetime

import pandas as pd
import pytest

from e2c_data.source import DataUnavailable, LookAheadError
from e2c_data.synthetic import make_synthetic_tables
from e2c_data.view import PointInTimeView


class Mem:
    """A five-line source: the port is that narrow."""

    def __init__(self, tables):
        self.tables = tables

    def read(self, kind, start=None, end=None, ids=None):
        if kind not in self.tables:
            raise DataUnavailable(kind)
        return self.tables[kind]


def accounts():
    return pd.DataFrame({
        "issuer_id": ["I1", "I1", "I1"],
        "period_end": pd.to_datetime(["2004-03-31", "2004-03-31", "2004-06-30"]),
        "available_at": pd.to_datetime(["2004-05-10", "2005-02-01", "2004-08-10"]),
        "total_liabilities": [100.0, 150.0, 110.0],
    })


def view(t, tables=None):
    return PointInTimeView(Mem(tables or {"accounts": accounts()}), t)


def test_read_keeps_the_latest_known_version_per_key():
    got = view(datetime(2005, 3, 1)).read("accounts").set_index("period_end").total_liabilities
    assert got[pd.Timestamp("2004-03-31")] == 150.0 and got[pd.Timestamp("2004-06-30")] == 110.0


def test_restated_value_never_appears_before_its_available_at():
    for t in pd.date_range("2004-05-10", "2005-01-31", freq="7D"):
        v = view(t.to_pydatetime())
        assert 150.0 not in set(v.read("accounts").total_liabilities)
        assert 150.0 not in set(v.versions("accounts").total_liabilities)
    assert 150.0 in set(view(datetime(2005, 2, 1)).read("accounts").total_liabilities)


def test_versions_keeps_every_version_known_so_far():
    assert sorted(view(datetime(2005, 3, 1)).versions("accounts").total_liabilities) == [100.0, 110.0, 150.0]
    assert sorted(view(datetime(2004, 9, 1)).versions("accounts").total_liabilities) == [100.0, 110.0]


def test_end_past_decision_time_raises_on_read_and_versions():
    v = view(datetime(2004, 9, 1))
    for f in (v.read, v.versions):
        with pytest.raises(LookAheadError):
            f("accounts", end=date(2004, 9, 2))
        assert len(f("accounts", end=date(2004, 9, 1))) >= 0


def test_missing_kind_raises_data_unavailable():
    with pytest.raises(DataUnavailable):
        view(datetime(2004, 9, 1)).read("rates")


def test_view_filters_even_if_the_source_ignores_the_window_and_ids():
    v = view(datetime(2005, 3, 1))
    assert len(v.read("accounts", start=date(2004, 6, 1))) == 1
    assert v.read("accounts", ids=["NOPE"]).empty


def test_unknown_available_at_counts_as_never_known():
    a = accounts()
    a.loc[2, "available_at"] = pd.NaT
    assert len(view(datetime(2030, 1, 1), {"accounts": a}).versions("accounts")) == 2


def test_source_without_available_at_is_rejected():
    with pytest.raises(ValueError, match="available_at"):
        view(datetime(2005, 1, 1), {"accounts": accounts().drop(columns="available_at")}).read("accounts")


def test_at_gives_another_time_and_leaves_the_first_alone():
    v = view(datetime(2005, 3, 1))
    assert len(v.at(datetime(2004, 9, 1)).versions("accounts")) == 2
    assert len(v.versions("accounts")) == 3


def test_result_is_a_copy():
    src = accounts()
    got = view(datetime(2005, 3, 1), {"accounts": src}).versions("accounts")
    got.loc[got.index[0], "total_liabilities"] = -1
    assert -1 not in set(src.total_liabilities)


def link_map():
    return pd.DataFrame({
        "instrument_id": ["B1", "B1", "B2"], "instrument_type": ["bond"] * 3, "issuer_id": ["I1", "I2", "I3"],
        "valid_from": pd.to_datetime(["2000-01-01", "2004-01-01", "2000-01-01"]),
        "valid_to": pd.to_datetime(["2003-12-31", pd.NaT, pd.NaT]),
        "available_at": pd.to_datetime(["2000-01-01", "2004-01-02", "2000-01-01"]),
    })


def test_issuers_on_resolves_by_date():
    v = view(datetime(2005, 1, 1), {"security_map": link_map()})
    got = v.issuers_on(["B1", "B2", "B9"], date(2003, 6, 1))
    assert got["B1"] == "I1" and got["B2"] == "I3" and pd.isna(got["B9"])
    assert v.issuers_on(["B1"], date(2004, 6, 1))["B1"] == "I2"


def test_issuers_on_does_not_see_a_link_not_yet_public():
    v = view(datetime(2004, 1, 1, 12), {"security_map": link_map()})  # the new link is public on 2 January
    assert pd.isna(v.issuers_on(["B1"], date(2004, 1, 1))["B1"])


def test_issuers_on_past_decision_time_raises():
    with pytest.raises(LookAheadError):
        view(datetime(2004, 1, 1), {"security_map": link_map()}).issuers_on(["B1"], date(2004, 1, 2))


def test_issuers_on_refuses_two_issuers_for_one_instrument():
    m = link_map()
    m.loc[0, "valid_to"] = pd.Timestamp("2004-06-30")
    with pytest.raises(ValueError, match="1 instrument"):
        view(datetime(2005, 1, 1), {"security_map": m}).issuers_on(["B1"], date(2004, 3, 1))


def test_works_on_synthetic_data_at_many_times():
    t = make_synthetic_tables()
    src = Mem(t)
    for when in (datetime(2003, 6, 30, 18), datetime(2005, 6, 30, 18)):
        v = PointInTimeView(src, when)
        for kind in t:
            assert (v.versions(kind).available_at <= pd.Timestamp(when)).all(), kind
            assert (v.read(kind).available_at <= pd.Timestamp(when)).all(), kind
