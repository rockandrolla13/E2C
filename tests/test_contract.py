"""check_source: a clean source passes, and each planted defect is caught by name. End to end from a folder."""
from datetime import datetime

import pandas as pd
import pytest

from e2c_data.contract import check_source, failures
from e2c_data.schema import KINDS, REQUIRED_KINDS
from e2c_data.source import DataUnavailable
from e2c_data.synthetic import make_synthetic_tables
from e2c_data.tables import TableSource, write_tables

WHEN = datetime(2005, 12, 30, 18)


class Mem:
    def __init__(self, tables):
        self.tables = tables

    def read(self, kind, start=None, end=None, ids=None):
        if kind not in self.tables:
            raise DataUnavailable(kind)
        return self.tables[kind].copy()


@pytest.fixture()
def tables():
    return make_synthetic_tables()


def failed(tables, when=WHEN):
    f = failures(check_source(Mem(tables), when))
    return set(zip(f.check, f.kind))


def test_clean_synthetic_source_passes(tables):
    assert failed(tables) == set()


def test_end_to_end_from_a_table_folder(tmp_path, tables):
    write_tables(tables, tmp_path)
    assert failures(check_source(TableSource(tmp_path), WHEN)).empty


def test_clean_early_decision_time_passes(tables):
    assert failed(tables, datetime(2004, 6, 30, 18)) == set()


# ---- planted defects


@pytest.mark.parametrize("kind,column", [("rates", "rate"), ("bond_terms", "coupon"), ("equity_prices", "realised_vol_30d"),
                                         ("cds_quotes", "spread"), ("option_quotes", "vendor_iv")])
def test_percent_stored_as_decimal(tables, kind, column):
    tables[kind][column] *= 100
    assert ("units", kind) in failed(tables)


def test_price_per_one_instead_of_per_hundred(tables):
    tables["bond_prices"]["clean_price"] /= 100
    assert ("units", "bond_prices") in failed(tables)


def test_amounts_in_millions_instead_of_usd(tables):
    tables["accounts"]["total_liabilities"] /= 1e6
    assert ("units", "accounts") in failed(tables)


def test_available_before_the_event_date(tables):
    a = tables["accounts"]
    a.loc[a.index[0], "available_at"] = a.period_end.iloc[0] - pd.Timedelta(30, "D")
    assert ("look_ahead", "accounts") in failed(tables)


def test_blank_available_at(tables):
    r = tables["rates"]
    r["available_at"] = r["available_at"].astype("datetime64[ns]")
    r.loc[r.index[0], "available_at"] = pd.NaT
    assert ("look_ahead", "rates") in failed(tables)


def test_early_announcement_is_allowed_for_events(tables):
    e = tables["events"]
    e["available_at"] = e.event_date - pd.Timedelta(30, "D")
    assert failed(tables) == set()


def test_link_cut_short_leaves_prices_unlinked(tables):
    m = tables["security_map"]
    i = m.index[m.instrument_id == "E001"]
    m.loc[i, "valid_to"] = pd.Timestamp("2004-01-01")
    assert ("links", "equity_prices") in failed(tables)


def test_link_to_an_unknown_issuer(tables):
    m = tables["security_map"]
    m.loc[m.instrument_id == "E002", "issuer_id"] = "GHOST"
    assert ("links", "security_map") in failed(tables)


def test_two_issuers_at_once(tables):
    m = tables["security_map"]
    extra = m[m.instrument_id == "E003"].assign(issuer_id="I001")
    tables["security_map"] = pd.concat([m, extra], ignore_index=True)
    assert ("links", "security_map") in failed(tables)


def test_prices_with_no_link_at_all(tables):
    m = tables["security_map"]
    tables["security_map"] = m[m.instrument_id != "E004"]
    assert ("links", "equity_prices") in failed(tables)


def _strip_dead(tables):
    dead = set(tables["universe"].dropna(subset=["end_date"]).issuer_id)
    m = tables["security_map"]
    gone = set(m[m.issuer_id.isin(dead)].instrument_id)
    out = {}
    for kind, df in tables.items():
        s = KINDS[kind]
        if "issuer_id" in df.columns:
            df = df[~df.issuer_id.isin(dead)]
        if s.id_column != "issuer_id" and s.id_column in df.columns:
            df = df[~df[s.id_column].isin(gone)]
        if kind == "option_quotes":
            df = df[~df.equity_id.isin(gone)]
        out[kind] = df
    return out


def test_dead_names_removed_everywhere(tables):
    assert ("survivorship", "universe") in failed(_strip_dead(tables))


def test_dead_names_removed_from_universe_only(tables):
    u = tables["universe"]
    tables["universe"] = u[u.groupby("issuer_id").end_date.transform("count") == 0]
    got = failed(tables)
    assert ("survivorship", "universe") in got


def test_events_name_an_issuer_missing_from_universe(tables):
    e = tables["events"]
    e.loc[e.index[0], "issuer_id"] = "GONE"
    assert ("survivorship", "universe") in failed(tables)


def test_too_little_history_is_not_judged(tables):
    u = _strip_dead(tables)["universe"]
    report = check_source(Mem({**_strip_dead(tables), "universe": u}), datetime(2003, 3, 1, 18))
    row = report[report.check == "survivorship"].iloc[0]
    assert row.passed and "not judged" in row.note


@pytest.mark.parametrize("kind", sorted(REQUIRED_KINDS))
def test_missing_required_kind(tables, kind):
    del tables[kind]
    assert ("present", kind) in failed(tables)


def test_missing_optional_kind_is_noted_not_failed(tables):
    del tables["option_quotes"]
    report = check_source(Mem(tables), WHEN)
    row = report[(report.check == "present") & (report.kind == "option_quotes")].iloc[0]
    assert not row.passed and row.level == "optional"
    assert not failures(report).kind.eq("option_quotes").any()


def test_empty_required_kind(tables):
    tables["rates"] = tables["rates"].iloc[0:0]
    assert ("present", "rates") in failed(tables)


def test_missing_required_column(tables):
    tables["bond_prices"] = tables["bond_prices"].drop(columns="clean_price")
    assert ("columns", "bond_prices") in failed(tables)


def test_duplicate_version(tables):
    r = tables["rates"]
    tables["rates"] = pd.concat([r, r.head(5)], ignore_index=True)
    assert ("keys", "rates") in failed(tables)


def test_factor_returns_missing_is_optional(tables):
    del tables["factor_returns"]
    assert failed(tables) == set()


def test_factor_returns_in_percent_is_caught(tables):
    tables["factor_returns"]["excess_return"] *= 100
    assert ("units", "factor_returns") in failed(tables)


# ---- hindsight: a warning, never a failure


def hindsight(tables, kind, when=WHEN):
    report = check_source(Mem(tables), when)
    row = report[(report.check == "hindsight") & (report.kind == kind)].iloc[0]
    return row, report


@pytest.mark.parametrize("kind", ["universe", "security_map"])
def test_clean_tables_give_no_hindsight_warning(tables, kind):
    row, _ = hindsight(tables, kind)
    assert row.level == "warn" and row.passed and row["count"] == 0


@pytest.mark.parametrize("kind,end", [("universe", "end_date"), ("security_map", "valid_to")])
def test_end_date_visible_before_it_happened_warns(tables, kind, end):
    t = tables[kind]
    rows = t.index[t[end].notna()]
    t.loc[rows, "available_at"] = t.loc[rows, end] - pd.Timedelta(400, "D")
    row, report = hindsight(tables, kind)
    assert row.level == "warn" and not row.passed and row["count"] == len(rows)
    assert not failures(report).check.eq("hindsight").any()
    assert failures(report, "warn").check.eq("hindsight").any()


def test_hindsight_counts_only_the_early_rows(tables):
    t = tables["universe"]
    rows = t.index[t.end_date.notna()][:1]
    t.loc[rows, "available_at"] = t.loc[rows, "end_date"] - pd.Timedelta(1, "D")
    assert hindsight(tables, "universe")[0]["count"] == 1


def test_one_snapshot_date_gives_no_evidence(tables):
    tables["universe"]["available_at"] = pd.Timestamp("2006-01-02")
    row, report = hindsight(tables, "universe")
    assert not row.passed and "no evidence" in row.note and row["count"] == tables["universe"].end_date.notna().sum()
    assert not failures(report).check.eq("hindsight").any()


def test_blank_available_at_on_an_ended_row_gives_no_evidence(tables):
    t = tables["security_map"]
    rows = t.index[t.valid_to.notna()][:2]
    t.loc[rows, "available_at"] = pd.NaT
    row, _ = hindsight(tables, "security_map")
    assert not row.passed and row["count"] == 2 and "no evidence" in row.note


def test_no_available_at_column_gives_no_evidence(tables):
    tables["universe"] = tables["universe"].drop(columns="available_at")
    row, report = hindsight(tables, "universe")
    assert row.level == "warn" and not row.passed and "no evidence" in row.note
    assert ("columns", "universe") in set(zip(failures(report).check, failures(report).kind))


def test_hindsight_report_has_counts_not_rows(tables):
    t = tables["universe"]
    t.loc[t.end_date.notna(), "available_at"] = pd.Timestamp("2000-01-03")
    text = hindsight(tables, "universe")[1].query("check == 'hindsight'").to_string()
    for secret in ("I007", "I008", "2003-11-14", "2004-03-19"):
        assert secret not in text


# ---- the report


def test_report_shape_and_counts_never_rows(tables):
    r = tables["rates"]
    r.loc[r.index[:7], "rate"] = 45.0
    report = check_source(Mem(tables), WHEN)
    assert list(report.columns) == ["check", "kind", "level", "passed", "count", "note"]
    assert report[(report.check == "units") & (report.kind == "rates")]["count"].iloc[0] >= 7
    text = report.to_string()
    for secret in ("E001", "I001", "B0011", "45.0"):
        assert secret not in text


def test_a_read_that_blows_up_is_reported(tables):
    class Bad(Mem):
        def read(self, kind, start=None, end=None, ids=None):
            if kind == "rates":
                raise OSError("disk")
            return super().read(kind, start, end, ids)
    f = failures(check_source(Bad(tables), WHEN))
    assert ("present", "rates") in set(zip(f.check, f.kind))
