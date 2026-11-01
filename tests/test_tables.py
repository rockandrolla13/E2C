"""TableSource: a folder of files, one per kind."""
import pandas as pd
import pytest

from e2c_data.schema import KINDS
from e2c_data.source import DataUnavailable, Source
from e2c_data.synthetic import make_synthetic_tables
from e2c_data.tables import TableSource, write_tables


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    root = tmp_path_factory.mktemp("tables")
    write_tables(make_synthetic_tables(), root)
    return root


def test_satisfies_the_port(folder):
    src: Source = TableSource(folder)
    assert not src.read("rates").empty


def test_missing_file_raises_data_unavailable(tmp_path):
    with pytest.raises(DataUnavailable, match="rates"):
        TableSource(tmp_path).read("rates")


def test_unknown_kind_is_a_clear_error(folder):
    with pytest.raises(ValueError, match="nonsense"):
        TableSource(folder).read("nonsense")


def test_returns_all_versions(folder):
    acc = TableSource(folder).read("accounts")
    assert acc.duplicated(["issuer_id", "period_end"]).any()


def test_window_and_ids_filter(folder):
    src = TableSource(folder)
    df = src.read("equity_prices", pd.Timestamp("2004-01-05").date(), pd.Timestamp("2004-01-09").date(), ["E001"])
    assert set(df.equity_id) == {"E001"}
    assert df.date.min() >= pd.Timestamp("2004-01-05") and df.date.max() <= pd.Timestamp("2004-01-09")
    assert len(df) == 5


def test_end_date_includes_intraday_rows_of_that_day(folder):
    src = TableSource(folder)
    full = src.read("bond_trades")
    day = full.execution_time.iloc[0].normalize()
    got = src.read("bond_trades", day.date(), day.date())
    assert len(got) == (full.execution_time.dt.normalize() == day).sum() > 0


def test_undated_kind_ignores_the_window(folder):
    src = TableSource(folder)
    assert len(src.read("bond_terms", pd.Timestamp("1990-01-01").date(), pd.Timestamp("1990-01-02").date())) == len(src.read("bond_terms"))


def test_dates_parse_and_ids_keep_leading_zeros(tmp_path):
    pd.DataFrame({"bond_id": ["00123"], "coupon": [0.05], "freq": [2], "maturity_date": ["2010-06-01"],
                  "issue_date": ["2000-06-01"], "available_at": ["2000-06-01"]}).to_csv(tmp_path / "bond_terms.csv", index=False)
    df = TableSource(tmp_path).read("bond_terms")
    assert df.bond_id.iloc[0] == "00123"
    assert pd.api.types.is_datetime64_any_dtype(df.maturity_date) and pd.api.types.is_datetime64_any_dtype(df.available_at)


def test_blank_stays_nan_not_zero(tmp_path):
    (tmp_path / "accounts.csv").write_text("issuer_id,period_end,available_at,total_liabilities\nI1,2004-03-31,2004-05-10,\n")
    assert TableSource(tmp_path).read("accounts").total_liabilities.isna().all()


def test_parquet_wins_when_both_exist(tmp_path):
    pytest.importorskip("pyarrow")
    t = {"rates": make_synthetic_tables()["rates"].head(3)}
    write_tables(t, tmp_path, fmt="parquet")
    (tmp_path / "rates.csv").write_text("date,curve,tenor,rate,available_at\n2000-01-03,x,1,0.01,2000-01-03\n")
    assert len(TableSource(tmp_path).read("rates")) == 3


def test_round_trip_keeps_every_kind(folder):
    t = make_synthetic_tables()
    src = TableSource(folder)
    for kind in KINDS:
        assert len(src.read(kind)) == len(t[kind]), kind
    a, b = t["accounts"], src.read("accounts")
    assert b.total_liabilities.sum() == pytest.approx(a.total_liabilities.sum())


def test_write_rejects_a_bad_format(tmp_path):
    with pytest.raises(ValueError, match="xlsx"):
        write_tables({}, tmp_path, fmt="xlsx")
