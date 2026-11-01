"""Pick the data source of a run in one place. This is the only module that reads the environment.

- E2C_SOURCE unset: read tables from the folder E2C_DATA_ROOT.
- E2C_SOURCE=package.module:function: call `function()` with no arguments. It returns any object with `read`. Your
  production adapter lives outside this repo and plugs in here.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path

from e2c_data.source import Source
from e2c_data.tables import TableSource

SOURCE_ENV = "E2C_SOURCE"
ROOT_ENV = "E2C_DATA_ROOT"


@dataclass(frozen=True)
class DataConfig:
    source: str | None
    data_root: Path | None

    @classmethod
    def from_env(cls) -> "DataConfig":
        root = os.environ.get(ROOT_ENV)
        return cls(source=os.environ.get(SOURCE_ENV) or None, data_root=Path(root) if root else None)


def open_source() -> Source:
    config = DataConfig.from_env()
    if config.source is None:
        if config.data_root is None:
            raise ValueError(f"set {ROOT_ENV} to a table folder, or {SOURCE_ENV} to module:function")
        return TableSource(config.data_root)
    module, _, name = config.source.partition(":")
    if not module or not name:
        raise ValueError(f"{SOURCE_ENV}={config.source!r}: use module:function")
    source = getattr(importlib.import_module(module), name)()
    if not callable(getattr(source, "read", None)):
        raise TypeError(f"{config.source} returned an object with no read method")
    return source
