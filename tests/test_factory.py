"""The factory: one setting picks the source, and only this module reads the environment."""
import ast
import pathlib
import sys

import pytest

import e2c_data
from e2c_data.factory import DataConfig, open_source
from e2c_data.tables import TableSource


def test_default_is_the_table_folder(monkeypatch, tmp_path):
    monkeypatch.delenv("E2C_SOURCE", raising=False)
    monkeypatch.setenv("E2C_DATA_ROOT", str(tmp_path))
    src = open_source()
    assert isinstance(src, TableSource) and src.root == tmp_path


def test_no_root_and_no_source_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("E2C_SOURCE", raising=False)
    monkeypatch.delenv("E2C_DATA_ROOT", raising=False)
    with pytest.raises(ValueError, match="E2C_DATA_ROOT"):
        open_source()


def test_module_path_loads_an_outside_adapter(monkeypatch, tmp_path):
    (tmp_path / "prod_adapter_for_test.py").write_text(
        "class S:\n    def read(self, kind, start=None, end=None, ids=None):\n        return kind\n"
        "def make_source():\n    return S()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("E2C_SOURCE", "prod_adapter_for_test:make_source")
    assert open_source().read("rates") == "rates"
    sys.modules.pop("prod_adapter_for_test", None)


@pytest.mark.parametrize("bad", ["no_colon", ":x", "mod:"])
def test_bad_setting_is_a_clear_error(monkeypatch, bad):
    monkeypatch.setenv("E2C_SOURCE", bad)
    with pytest.raises(ValueError, match="module:function"):
        open_source()


def test_adapter_without_read_is_rejected(monkeypatch, tmp_path):
    (tmp_path / "bad_adapter_for_test.py").write_text("def make_source():\n    return object()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("E2C_SOURCE", "bad_adapter_for_test:make_source")
    with pytest.raises(TypeError, match="read"):
        open_source()
    sys.modules.pop("bad_adapter_for_test", None)


def test_config_is_frozen():
    c = DataConfig(source=None, data_root=None)
    with pytest.raises(AttributeError):
        c.source = "x"


def test_only_the_factory_reads_the_environment():
    readers = []
    for path in pathlib.Path(e2c_data.__file__).parent.glob("*.py"):
        for n in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) else []
            if "os" in names or "environ" in getattr(n, "attr", "") or "getenv" in getattr(n, "attr", ""):
                readers.append(path.name)
    assert set(readers) <= {"factory.py"}
