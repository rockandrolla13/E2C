"""The port every source meets, and the two data errors."""
from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence

import pandas as pd

from e2c_data.schema import KindSpec


class DataUnavailable(LookupError):
    """The source does not hold a required kind."""


class LookAheadError(ValueError):
    """A read asked for data past the decision time."""


class Source(Protocol):
    """Anything that serves every version of a data kind."""

    def read(
        self,
        kind: str,
        start: date | None = None,
        end: date | None = None,
        ids: Sequence[str] | None = None,
    ) -> pd.DataFrame: ...


def restrict(df: pd.DataFrame, spec: KindSpec, start: date | None, end: date | None,
             ids: Sequence[str] | None) -> pd.DataFrame:
    """Rows inside the window and ids. `end` includes that whole day. An undated kind ignores the window."""
    if spec.date_column is not None:
        if start is not None:
            df = df[df[spec.date_column] >= pd.Timestamp(start).normalize()]
        if end is not None:
            df = df[df[spec.date_column] < pd.Timestamp(end).normalize() + pd.Timedelta(1, "D")]
    if ids is not None:
        df = df[df[spec.id_column].isin(list(ids))]
    return df
