"""Test a source before trusting it. Each check returns report rows. The report holds counts, never data rows.

Run `failures(check_source(source, decision_time))`. An empty result means no check found a problem. It does not
mean the data is right: these checks see missing kinds, wrong units, look-ahead, broken links and missing dead names.
A hindsight row has level warn, so `failures` leaves it out by default. Read it with `failures(report, "warn")`.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from e2c_data.schema import ANNOUNCED_EARLY, KINDS, RANGES, REQUIRED_KINDS, TERMINAL_EVENTS
from e2c_data.source import DataUnavailable, Source
from e2c_data.view import PointInTimeView

REPORT_COLUMNS = ["check", "kind", "level", "passed", "count", "note"]
MIN_NAMES_TO_JUDGE = 5
MIN_DAYS_TO_JUDGE = 365

# kind -> the column that names an instrument in security_map
_LINKED = {"equity_prices": "equity_id", "bond_prices": "bond_id", "bond_trades": "bond_id", "bond_terms": "bond_id",
           "option_quotes": "equity_id"}
_ISSUER_KINDS = ("issuer_attributes", "accounts", "cds_quotes")
_END_COLUMNS = {"universe": "end_date", "security_map": "valid_to"}


def _row(check: str, kind: str, count: int, note: str = "", level: str = "required") -> dict:
    return dict(check=check, kind=kind, level=level, passed=count == 0, count=int(count), note=note)


class _Raw:
    """Every kind read once, so the checks and the view look at the same rows."""

    def __init__(self, source: Source, when: datetime) -> None:
        self.tables: dict[str, pd.DataFrame] = {}
        self.errors: dict[str, str] = {}
        for kind in KINDS:
            try:
                self.tables[kind] = source.read(kind).copy()
            except DataUnavailable:
                self.errors[kind] = "not in the source"
            except Exception as e:  # a broken source must show up in the report, not stop the check
                self.errors[kind] = f"read failed: {type(e).__name__}"
        self.view = PointInTimeView(self, when)

    def read(self, kind, start=None, end=None, ids=None):
        if kind not in self.tables:
            raise DataUnavailable(kind)
        return self.tables[kind]

    def usable(self, kind: str) -> bool:
        return kind in self.tables and set(KINDS[kind].required) <= set(self.tables[kind].columns)


def _check_present(raw: _Raw) -> list[dict]:
    rows = []
    for kind in KINDS:
        level = "required" if kind in REQUIRED_KINDS else "optional"
        n = len(raw.tables[kind]) if kind in raw.tables else 0
        note = raw.errors.get(kind, "empty" if n == 0 else "")
        rows.append(dict(check="present", kind=kind, level=level, passed=n > 0, count=n, note=note))
    return rows


def _check_columns(raw: _Raw) -> list[dict]:
    rows = []
    for kind, df in raw.tables.items():
        missing = sorted(set(KINDS[kind].required) - set(df.columns))
        rows.append(_row("columns", kind, len(missing), ", ".join(missing)))
    return rows


def _check_keys(raw: _Raw) -> list[dict]:
    rows = []
    for kind in raw.tables:
        if raw.usable(kind):
            n = raw.tables[kind].duplicated(list(KINDS[kind].key) + ["available_at"]).sum()
            rows.append(_row("keys", kind, n, "rows sharing a key and an available_at" if n else ""))
    return rows


def _check_units(raw: _Raw) -> list[dict]:
    rows = []
    for kind in raw.tables:
        if not raw.usable(kind):
            continue
        df, count, bad = raw.view.read(kind), 0, []
        for c in sorted(set(df.columns) & set(RANGES)):
            r, x = RANGES[c], pd.to_numeric(df[c], errors="coerce").dropna()
            if x.empty:
                continue
            outside = int(((x < r.lo) | (x > r.hi)).sum())
            if not r.median_lo <= x.median() <= r.median_hi:
                outside = max(outside, len(x))
            if outside:
                count, bad = count + outside, bad + [c]
        rows.append(_row("units", kind, count, ", ".join(bad)))
    return rows


def _check_look_ahead(raw: _Raw) -> list[dict]:
    rows = []
    for kind in raw.tables:
        if not raw.usable(kind):
            continue
        spec, df = KINDS[kind], raw.tables[kind]
        at = pd.to_datetime(df["available_at"])
        count, notes = int(at.isna().sum()), ["blank available_at"] if at.isna().any() else []
        if spec.date_column is not None and kind not in ANNOUNCED_EARLY:
            early = int((at < pd.to_datetime(df[spec.date_column])).sum())
            if early:
                count, notes = count + early, notes + [f"available_at before {spec.date_column}"]
        rows.append(_row("look_ahead", kind, count, ", ".join(notes)))
    return rows


def _check_links(raw: _Raw) -> list[dict]:
    if not raw.usable("security_map"):
        return []
    links = raw.view.read("security_map")
    rows = [_map_problems(raw, links)]
    for kind, id_column in _LINKED.items():
        if raw.usable(kind):
            rows.append(_unlinked(kind, raw.view.read(kind), id_column, links))
    return rows


def _map_problems(raw: _Raw, links: pd.DataFrame) -> dict:
    spec = KINDS["security_map"]
    versions = raw.view.versions("security_map")
    tied = versions.drop_duplicates(list(spec.key) + ["available_at", "issuer_id"]).duplicated(list(spec.key) + ["available_at"]).sum()
    a = links.merge(links, on="instrument_id", suffixes=("", "_other"))
    far = pd.Timestamp.max
    overlap = (a.valid_from < a.valid_from_other) & (a.valid_to.fillna(far) >= a.valid_from_other) & (a.issuer_id != a.issuer_id_other)
    unknown = 0
    if raw.usable("universe"):
        unknown = int((~links.issuer_id.isin(raw.view.read("universe").issuer_id)).sum())
    count, notes = int(tied + overlap.sum()) + unknown, []
    if tied or overlap.any():
        notes.append("two issuers at once")
    if unknown:
        notes.append("issuer not in universe")
    return _row("links", "security_map", count, ", ".join(notes))


def _unlinked(kind: str, df: pd.DataFrame, id_column: str, links: pd.DataFrame) -> dict:
    """Count (instrument, day) pairs with no link covering that day."""
    date_column = KINDS[kind].date_column
    if date_column is None:
        n = (~df[id_column].isin(links.instrument_id)).sum()
        return _row("links", kind, n, "instrument with no link" if n else "")
    pairs = pd.DataFrame({"instrument_id": df[id_column], "day": pd.to_datetime(df[date_column]).dt.normalize()}).drop_duplicates()
    m = pairs.merge(links[["instrument_id", "valid_from", "valid_to"]], on="instrument_id", how="left")
    m["covered"] = (m.valid_from <= m.day) & (m.valid_to.isna() | (m.day <= m.valid_to))
    n = (~m.groupby(["instrument_id", "day"]).covered.any()).sum()
    return _row("links", kind, n, "days with no link" if n else "")


def _check_survivorship(raw: _Raw) -> list[dict]:
    if not raw.usable("universe"):
        return []
    universe = raw.view.read("universe")
    missing = 0
    if raw.usable("events"):
        e = raw.view.read("events")
        e = e[e.event_type.isin(TERMINAL_EVENTS) & (e.event_date <= raw.view.decision_time)]
        ended = universe.dropna(subset=["end_date"]).issuer_id
        missing = e.issuer_id[~e.issuer_id.isin(ended)].nunique()
    for kind in _ISSUER_KINDS:
        if raw.usable(kind):
            missing += raw.view.read(kind).issuer_id[lambda s: ~s.isin(universe.issuer_id)].nunique()
    if missing:
        return [_row("survivorship", "universe", missing, "names with an ending or data but no matching universe row")]
    names, dead = universe.issuer_id.nunique(), universe.end_date.notna().sum()
    days = 0
    if raw.usable("equity_prices") and len(prices := raw.view.read("equity_prices")):
        days = (raw.view.decision_time - pd.to_datetime(prices.date).min()).days
    if names < MIN_NAMES_TO_JUDGE or days < MIN_DAYS_TO_JUDGE:
        return [_row("survivorship", "universe", 0, "not judged: too few names or too little history")]
    return [_row("survivorship", "universe", names if dead == 0 else 0, "no name ever ended" if dead == 0 else "")]


def _check_hindsight(raw: _Raw) -> list[dict]:
    """A warning, never a failure. An end date seen before it happened may be an announcement, or a vendor's hindsight."""
    rows = []
    for kind, end in _END_COLUMNS.items():
        if kind not in raw.tables or end not in raw.tables[kind].columns:
            continue
        df = raw.tables[kind]
        ended = df[df[end].notna()]
        rows.append(_hindsight_row(kind, df, ended, end))
    return rows


def _hindsight_row(kind: str, df: pd.DataFrame, ended: pd.DataFrame, end: str) -> dict:
    if ended.empty:
        return _row("hindsight", kind, 0, level="warn")
    if "available_at" not in df.columns:
        return _row("hindsight", kind, len(ended), "no evidence: no available_at column", "warn")
    if pd.to_datetime(df["available_at"]).nunique() <= 1:
        return _row("hindsight", kind, len(ended), "no evidence: one available_at on every row", "warn")
    at, when = pd.to_datetime(ended["available_at"]), pd.to_datetime(ended[end])
    blank, early = int(at.isna().sum()), int((at < when).sum())
    notes = ["no evidence: blank available_at"] if blank else []
    if early:
        notes.append(f"{end} visible before it happened")
    return _row("hindsight", kind, blank + early, ", ".join(notes), "warn")


CHECKS = (_check_present, _check_columns, _check_keys, _check_units, _check_look_ahead, _check_links, _check_survivorship,
          _check_hindsight)


def check_source(source: Source, decision_time: datetime) -> pd.DataFrame:
    """One row per check and kind. `count` is how many rows, values or names failed. Present counts rows held."""
    raw = _Raw(source, decision_time)
    return pd.DataFrame([row for check in CHECKS for row in check(raw)], columns=REPORT_COLUMNS)


def failures(report: pd.DataFrame, level: str = "required") -> pd.DataFrame:
    return report[~report.passed & (report.level == level)].reset_index(drop=True)
