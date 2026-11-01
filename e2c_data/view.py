"""PointInTimeView: what was known at one decision time. A frozen copy of the world on the morning of the call.

Every method reads through a view. `read` gives the latest known version of each row. A backtest over many dates uses
`versions`, because the latest version known at the last date would put restated numbers on earlier dates. A view is
read-only, so names and dates can run in parallel with one view per worker.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

import pandas as pd

from e2c_data.schema import kind_spec
from e2c_data.source import LookAheadError, Source, restrict


class PointInTimeView:
    def __init__(self, source: Source, decision_time: datetime) -> None:
        self.source = source
        self.decision_time = pd.Timestamp(decision_time)

    def at(self, decision_time: datetime) -> "PointInTimeView":
        """The same source at another decision time."""
        return PointInTimeView(self.source, decision_time)

    def read(self, kind: str, start: date | None = None, end: date | None = None,
             ids: Sequence[str] | None = None) -> pd.DataFrame:
        """The latest version of each row known at the decision time."""
        df = self.versions(kind, start, end, ids)
        return df.drop_duplicates(list(kind_spec(kind).key), keep="last").reset_index(drop=True)

    def versions(self, kind: str, start: date | None = None, end: date | None = None,
                 ids: Sequence[str] | None = None) -> pd.DataFrame:
        """Every version known at the decision time, oldest first within each key."""
        spec = kind_spec(kind)
        self._guard(end)
        df = self.source.read(kind, start, end, ids)
        if "available_at" not in df.columns:
            raise ValueError(f"{kind}: the source gave no available_at column")
        df = restrict(df, spec, start, end, ids)  # a source may ignore the window, and the view does not trust it
        df = df[pd.to_datetime(df["available_at"]) <= self.decision_time]  # a blank available_at is never known
        return df.sort_values(list(spec.key) + ["available_at"], kind="stable").reset_index(drop=True).copy()

    def issuers_on(self, ids: Sequence[str], on: date) -> pd.Series:
        """The issuer of each instrument on one date, as known now. NaN if none. Two at once is an error."""
        self._guard(on)
        when = pd.Timestamp(on).normalize()
        m = self.read("security_map", ids=ids)
        m = m[(m.valid_from <= when) & (m.valid_to.isna() | (m.valid_to >= when))]
        clashes = m.groupby("instrument_id").issuer_id.nunique().gt(1).sum()
        if clashes:
            raise ValueError(f"{clashes} instrument(s) have two issuers on {when.date()}")
        return m.set_index("instrument_id").issuer_id.reindex(list(ids))

    def _guard(self, end: date | None) -> None:
        if end is not None and pd.Timestamp(end).normalize() > self.decision_time.normalize():
            raise LookAheadError(f"read to {pd.Timestamp(end).date()} is past the decision time {self.decision_time}")
