"""Point-in-time data layer for the E2C methods. It holds no data and no production adapter."""
from e2c_data.contract import check_source, failures
from e2c_data.factory import open_source
from e2c_data.schema import KINDS, KindSpec
from e2c_data.source import DataUnavailable, LookAheadError, Source
from e2c_data.synthetic import make_synthetic_tables
from e2c_data.tables import TableSource, write_tables
from e2c_data.view import PointInTimeView

__all__ = ["DataUnavailable", "KINDS", "KindSpec", "LookAheadError", "PointInTimeView", "Source", "TableSource",
           "check_source", "failures", "make_synthetic_tables", "open_source", "write_tables"]
