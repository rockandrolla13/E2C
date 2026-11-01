"""A source that reads plain tables: the easy way to plug in any data.

Put one file per kind in a folder, named `<kind>.parquet` or `<kind>.csv`. Parquet wins when both exist. Columns and
units are in `schema.py`. A kind with no file raises DataUnavailable.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from e2c_data.schema import COLUMNS, kind_spec
from e2c_data.source import DataUnavailable, restrict

_BOOLS = {"True": True, "False": False, "true": True, "false": False, True: True, False: False}


class TableSource:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def read(self, kind: str, start: date | None = None, end: date | None = None,
             ids: Sequence[str] | None = None) -> pd.DataFrame:
        spec = kind_spec(kind)
        return restrict(_typed(self._load(kind)), spec, start, end, ids).reset_index(drop=True)

    def _load(self, kind: str) -> pd.DataFrame:
        parquet, csv = self.root / f"{kind}.parquet", self.root / f"{kind}.csv"
        if parquet.exists():
            return pd.read_parquet(parquet)
        if csv.exists():
            # text columns stay text, so an id such as 00123 keeps its leading zeros
            return pd.read_csv(csv, dtype={c: str for c, col in COLUMNS.items() if col.type == "text"})
        raise DataUnavailable(f"{kind}: no {parquet.name} or {csv.name} in the table folder")


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    for c in df.columns:
        column = COLUMNS.get(c)
        if column is None:
            continue
        if column.type == "date":
            df[c] = pd.to_datetime(df[c])
        elif column.type == "bool" and df[c].dtype == object:
            df[c] = df[c].map(_BOOLS)
    return df


def write_tables(tables: Mapping[str, pd.DataFrame], root: str | Path, fmt: str = "csv") -> None:
    """Write one file per kind. CSV needs no extra package. Parquet needs pyarrow."""
    if fmt not in ("csv", "parquet"):
        raise ValueError(f"unknown format {fmt!r}. Use csv or parquet")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for kind, df in tables.items():
        kind_spec(kind)
        if fmt == "csv":
            df.to_csv(root / f"{kind}.csv", index=False)
        else:
            df.to_parquet(root / f"{kind}.parquet", index=False)
