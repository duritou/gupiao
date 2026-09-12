"""Build a frontend from a snapshot and bind it to one backend manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(manifest_path: Path, project_root: Path) -> dict:
    manifest = json.loads(manifest_path.read_text("utf-8-sig"))
    container = manifest_path.parent
    frontend = container / "frontend"
    if frontend.exists():
        raise RuntimeError("frontend snapshot already exists; create a new release")
    source = project_root / "vscode-ext"
    frontend.mkdir()
    for directory in ("src", "resources"):
        shutil.copytree(source / directory, frontend / directory)
    for filename in ("package.json", "tsconfig.json", "README.md", ".vscodeignore"):
        shutil.copy2(source / filename, frontend / filename)
    package = json.loads((frontend / "package.json").read_text("utf-8"))
    package["version"] = manifest["product_version"]
    (frontend / "package.json").write_text(json.dumps(package, indent=2) + "\n", "utf-8")
    stamp = {
        "product_version": manifest["product_version"],
        "release_id": manifest["release_id"],
        "backend_artifact_hash": manifest["artifact_hash"],
        "api_contract_version": manifest["api_contract_version"],
    }
    (frontend / "release-info.json").write_text(json.dumps(stamp, indent=2) + "\n", "utf-8")
    node = shutil.which("node")
    vsce = shutil.which("vsce.cmd") or shutil.which("vsce")
    if not node or not vsce:
        raise RuntimeError("node and vsce must be installed before deployment")
    subprocess.run([
        node, str(source / "node_modules/typescript/bin/tsc"),
        "-p", str(frontend), "--typeRoots", str(source / "node_modules/@types"),
    ], check=True)
    vsix = container / f"adaptive-{manifest['release_id']}.vsix"
    subprocess.run([
        vsce, "package", "--no-dependencies", "--allow-missing-repository",
        "--out", str(vsix),
    ], cwd=frontend, check=True)
    launcher = project_root.parent / "scripts/start_adaptive_learning_backend.ps1"
    shutil.copy2(launcher, container / launcher.name)
    bundle = {
        **stamp,
        "frontend_vsix": str(vsix),
        "frontend_sha256": digest(vsix),
        "frontend_files": {
            path.relative_to(frontend).as_posix(): digest(path)
            for path in sorted((frontend / "out").rglob("*.js"))
        },
        "launcher_sha256": digest(container / launcher.name),
    }
    (container / "bundle.json").write_text(json.dumps(bundle, indent=2) + "\n", "utf-8")
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest.resolve(), Path(__file__).resolve().parents[1])))
