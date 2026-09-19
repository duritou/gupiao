"""Runtime release identity and startup drift checks.

The API process must report the code it started with.  A disk hash is used only
as a drift signal; it is never presented as proof that the running process
changed its code after startup.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_ENV = "ADAPTIVE_RELEASE_MANIFEST"
_BOOT_ID = uuid.uuid4().hex
_PROCESS_STARTED_AT = datetime.now().astimezone().isoformat()
_STARTUP_IDENTITY: dict[str, Any] | None = None

CRITICAL_FILES = (
    "scripts/run_api.py",
    "scripts/backfill_research_data.py",
    "config/settings.py",
    "config/release.json",
    "src/api/app.py",
    "src/api/routes/system_routes.py",
    "src/api/routes/scanner_routes.py",
    "src/api/routes/ai_os_routes.py",
    "src/api/routes/decision_routes.py",
    "src/api/routes/signals_routes.py",
    "src/api/routes/journal_utils.py",
    "src/infrastructure/market_data/real_data_provider.py",
    "src/ai_os/strategy_version.py",
    "src/ai_os/recommendation_quality.py",
    "src/ai_os/candidate_evidence_enricher.py",
    "src/ai_os/pipeline_runner.py",
    "src/infrastructure/runtime_identity.py",
    "src/infrastructure/storage/market_database.py",
    "src/infrastructure/market_data/source_manager.py",
    "src/infrastructure/market_data/vibe_embedded.py",
    "src/infrastructure/market_data/tushare_provider.py",
    "src/infrastructure/market_data/flow_batch_backfill.py",
    "src/explain/outcome_backfiller.py",
    "pyproject.toml",
    "poetry.lock",
)


class RuntimeIdentityError(RuntimeError):
    """Raised when a managed process cannot prove its expected release."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _root_from_module() -> Path:
    return Path(__file__).resolve().parents[2]


def _file_entries(root: Path) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    paths = set(CRITICAL_FILES)
    shared = root.parent / "shared"
    paths.update(
        f"../shared/{path.relative_to(shared).as_posix()}"
        for path in shared.rglob("*.py") if "__pycache__" not in path.parts
    )
    for directory in ("src", "config", "scripts", "providers", "plugins", "knowledge"):
        paths.update(
            path.relative_to(root).as_posix()
            for path in (root / directory).rglob("*")
            if path.is_file() and path.suffix in {".py", ".ps1", ".json", ".yaml", ".yml", ".md"}
            and "__pycache__" not in path.parts
        )
    for relative in sorted(paths):
        path = root / relative
        if not path.is_file():
            raise RuntimeIdentityError(f"critical runtime file missing: {relative}")
        entries.append({"path": relative, "sha256": _sha256(path)})
    return entries


def _artifact_hash(entries: list[dict[str, str]]) -> str:
    payload = json.dumps(entries, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def create_manifest(root: str | Path, release_id: str | None = None) -> dict[str, Any]:
    """Create a deterministic manifest for the current worktree."""
    project_root = Path(root).resolve()
    entries = _file_entries(project_root)
    artifact_hash = _artifact_hash(entries)
    release_path = project_root / "config/release.json"
    release = json.loads(release_path.read_text("utf-8")) if release_path.exists() else {}
    return {
        "manifest_version": 1,
        "release_id": release_id or f"worktree-{artifact_hash[:16]}",
        "created_at": datetime.now().astimezone().isoformat(),
        "algorithm_version": "2.3.0-evidence-integrity",
        "schema_version": 5,
        "hash_scope": "runtime_source_files",
        "product_version": release.get("product_version", ""),
        "api_contract_version": release.get("api_contract_version", 1),
        "source_root": str(project_root),
        "python_executable": sys.executable,
        "files": entries,
        "artifact_hash": artifact_hash,
    }


def read_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeIdentityError(f"cannot read release manifest: {manifest_path}") from exc
    if not isinstance(value, dict) or not value.get("release_id"):
        raise RuntimeIdentityError("release manifest is missing release_id")
    return value


def validate_manifest(path: str | Path, root: str | Path | None = None) -> dict[str, Any]:
    """Validate a manifest against the files visible to this interpreter."""
    manifest = read_manifest(path)
    project_root = Path(root or _root_from_module()).resolve()
    declared_root = str(manifest.get("source_root") or "").strip()
    if declared_root and Path(declared_root).resolve() != project_root:
        raise RuntimeIdentityError("runtime manifest source root mismatch")
    expected = manifest.get("files")
    if not isinstance(expected, list) or not expected:
        raise RuntimeIdentityError("release manifest has no file entries")
    actual = _file_entries(project_root)
    expected_by_path = {str(item.get("path")): str(item.get("sha256")) for item in expected}
    actual_by_path = {item["path"]: item["sha256"] for item in actual}
    if expected_by_path != actual_by_path:
        changed = sorted(
            path for path in set(expected_by_path) | set(actual_by_path)
            if expected_by_path.get(path) != actual_by_path.get(path)
        )
        raise RuntimeIdentityError(f"runtime manifest mismatch: {', '.join(changed[:8])}")
    actual_artifact = _artifact_hash(actual)
    if actual_artifact != str(manifest.get("artifact_hash")):
        raise RuntimeIdentityError("runtime artifact hash mismatch")
    return manifest


def manifest_path() -> Path | None:
    value = os.environ.get(MANIFEST_ENV, "").strip()
    return Path(value).resolve() if value else None


def _current_artifact(root: Path) -> tuple[str | None, str | None]:
    try:
        entries = _file_entries(root)
        return _artifact_hash(entries), None
    except RuntimeIdentityError as exc:
        return None, str(exc)


def startup_identity() -> dict[str, Any]:
    """Return the identity frozen at import time plus a separate drift signal."""
    root = _root_from_module()
    if _STARTUP_IDENTITY is not None:
        current_artifact, drift_error = _current_artifact(root)
        return {
            **_STARTUP_IDENTITY,
            "disk_drift": current_artifact != _STARTUP_IDENTITY.get("artifact_hash"),
            "disk_check_error": drift_error or "",
        }
    configured_manifest = manifest_path()
    manifest: dict[str, Any] | None = None
    startup_error = ""
    if configured_manifest:
        try:
            manifest = validate_manifest(configured_manifest, root)
        except RuntimeIdentityError as exc:
            startup_error = str(exc)
    current_artifact, drift_error = _current_artifact(root)
    startup_artifact = str(manifest.get("artifact_hash")) if manifest else current_artifact
    return {
        "managed": bool(configured_manifest),
        "deployment_ready": bool(configured_manifest and not startup_error),
        "release_id": manifest.get("release_id") if manifest else None,
        "product_version": manifest.get("product_version") if manifest else None,
        "api_contract_version": manifest.get("api_contract_version") if manifest else None,
        "artifact_hash": startup_artifact,
        "hash_scope": manifest.get("hash_scope") if manifest else "critical_runtime_files",
        "algorithm_version": (
            manifest.get("algorithm_version")
            if manifest
            else "2.3.0-evidence-integrity"
        ),
        "schema_version": manifest.get("schema_version") if manifest else 5,
        "pid": os.getpid(),
        "boot_id": _BOOT_ID,
        "process_started_at": _PROCESS_STARTED_AT,
        "code_root": str(root),
        "python_executable": sys.executable,
        "manifest_path": str(configured_manifest) if configured_manifest else None,
        "startup_error": startup_error,
        "disk_drift": bool(
            current_artifact and startup_artifact and current_artifact != startup_artifact
        ),
        "disk_check_error": drift_error or "",
    }


def validate_startup_if_managed() -> dict[str, Any]:
    """Fail closed only when the launcher explicitly selected a manifest."""
    global _STARTUP_IDENTITY
    identity = startup_identity()
    if identity["managed"] and not identity["deployment_ready"]:
        raise RuntimeIdentityError(str(identity["startup_error"] or "runtime manifest rejected"))
    _STARTUP_IDENTITY = dict(identity)
    return identity
