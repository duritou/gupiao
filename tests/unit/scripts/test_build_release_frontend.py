from pathlib import Path

import pytest

from scripts.build_release_frontend import runtime_endpoint


def test_runtime_endpoint_reads_shared_config(tmp_path: Path) -> None:
    project_root = tmp_path / "adaptive-investment-intelligence"
    project_root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (config / "runtime.env").write_text(
        "ADAPTIVE_API_HOST=127.0.0.2\nADAPTIVE_API_PORT=8899\n", encoding="utf-8"
    )

    assert runtime_endpoint(project_root) == ("127.0.0.2", 8899)


def test_runtime_endpoint_rejects_invalid_port(tmp_path: Path) -> None:
    project_root = tmp_path / "adaptive-investment-intelligence"
    project_root.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    (config / "runtime.env").write_text("ADAPTIVE_API_PORT=70000\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside"):
        runtime_endpoint(project_root)
