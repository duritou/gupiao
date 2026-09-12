from __future__ import annotations

import json

import pytest

from src.infrastructure import runtime_identity


@pytest.fixture(autouse=True)
def isolated_boot_identity(monkeypatch):
    monkeypatch.setattr(runtime_identity, "_STARTUP_IDENTITY", None)


def test_manifest_round_trip_and_artifact_drift_detection(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_identity, "CRITICAL_FILES", ("src/a.py", "config/b.yaml"))
    (tmp_path / "src").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "src/a.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "config/b.yaml").write_text("enabled: true\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"

    manifest = runtime_identity.create_manifest(tmp_path, "test-release")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    assert runtime_identity.validate_manifest(manifest_path, tmp_path)["release_id"] == "test-release"
    (tmp_path / "src/a.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(runtime_identity.RuntimeIdentityError, match="runtime manifest mismatch"):
        runtime_identity.validate_manifest(manifest_path, tmp_path)


def test_managed_startup_rejects_bad_manifest(monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{\"release_id\": \"broken\"}", encoding="utf-8")
    monkeypatch.setenv(runtime_identity.MANIFEST_ENV, str(manifest_path))

    with pytest.raises(runtime_identity.RuntimeIdentityError, match="release manifest has no file entries"):
        runtime_identity.validate_startup_if_managed()


def test_unmanaged_identity_is_explicit(monkeypatch):
    monkeypatch.delenv(runtime_identity.MANIFEST_ENV, raising=False)

    identity = runtime_identity.startup_identity()

    assert identity["managed"] is False
    assert identity["deployment_ready"] is False
    assert identity["pid"] > 0
    assert identity["boot_id"]


def test_started_release_does_not_change_when_manifest_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_identity, "CRITICAL_FILES", ("src/a.py",))
    monkeypatch.setattr(runtime_identity, "_root_from_module", lambda: tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("value = 1\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(runtime_identity.create_manifest(tmp_path, "first")))
    monkeypatch.setenv(runtime_identity.MANIFEST_ENV, str(manifest_path))
    runtime_identity.validate_startup_if_managed()
    (tmp_path / "src/a.py").write_text("value = 2\n", encoding="utf-8")
    manifest_path.write_text(json.dumps(runtime_identity.create_manifest(tmp_path, "second")))
    identity = runtime_identity.startup_identity()
    assert identity["release_id"] == "first"
    assert identity["disk_drift"] is True


def test_unlisted_runtime_source_is_still_hashed(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_identity, "CRITICAL_FILES", ())
    (tmp_path / "src").mkdir()
    source = tmp_path / "src/not_in_critical_list.py"
    source.write_text("value = 1\n", encoding="utf-8")
    first = runtime_identity.create_manifest(tmp_path)
    source.write_text("value = 2\n", encoding="utf-8")
    assert runtime_identity.create_manifest(tmp_path)["artifact_hash"] != first["artifact_hash"]
