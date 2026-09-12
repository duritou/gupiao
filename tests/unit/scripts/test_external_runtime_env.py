from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "shared/python"))
from investment_common.runtime import load_runtime_env


@pytest.fixture
def layout(tmp_path, monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("INVESTMENT_LOCAL_ENV_FILE", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/runtime.env").write_text("", encoding="utf-8")
    install = tmp_path / "adaptive"
    release = install / "runtime/releases/test/adaptive"
    release.mkdir(parents=True)
    (install / ".env").write_text("TUSHARE_TOKEN=synthetic-local\n", encoding="utf-8")
    return install, release


def test_release_reads_explicit_original_env(layout, monkeypatch):
    import os
    install, release = layout
    monkeypatch.setenv("INVESTMENT_LOCAL_ENV_FILE", str(install / ".env"))
    load_runtime_env(release)
    assert os.environ["TUSHARE_TOKEN"] == "synthetic-local"
    assert not (release / ".env").exists()


def test_process_value_keeps_precedence(layout, monkeypatch):
    import os
    install, release = layout
    monkeypatch.setenv("INVESTMENT_LOCAL_ENV_FILE", str(install / ".env"))
    monkeypatch.setenv("TUSHARE_TOKEN", "synthetic-process")
    load_runtime_env(release)
    assert os.environ["TUSHARE_TOKEN"] == "synthetic-process"


@pytest.mark.parametrize("path", ["relative.env", "missing.env"])
def test_explicit_invalid_path_fails(layout, monkeypatch, path):
    install, release = layout
    value = path if path == "relative.env" else str(install / path)
    monkeypatch.setenv("INVESTMENT_LOCAL_ENV_FILE", value)
    with pytest.raises(RuntimeError, match="explicit local environment"):
        load_runtime_env(release)


def test_unmanaged_local_loading_unchanged(layout):
    import os
    install, _ = layout
    load_runtime_env(install)
    assert os.environ["TUSHARE_TOKEN"] == "synthetic-local"
