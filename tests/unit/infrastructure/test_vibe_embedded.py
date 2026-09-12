from pathlib import Path

from src.infrastructure.market_data import vibe_embedded


def test_embedded_vibe_discovers_backend_from_release_layout(tmp_path, monkeypatch):
    release_module = (
        tmp_path
        / "runtime"
        / "releases"
        / "release-test"
        / "adaptive-investment-intelligence"
        / "src"
        / "infrastructure"
        / "market_data"
        / "vibe_embedded.py"
    )
    release_module.parent.mkdir(parents=True)
    release_module.touch()
    backend = tmp_path / "vibe-research" / "backend"
    backend.mkdir(parents=True)

    monkeypatch.setattr(vibe_embedded, "__file__", str(release_module))
    monkeypatch.delenv("VIBE_BACKEND_ROOT", raising=False)
    monkeypatch.delenv("VIBE_RESEARCH_BACKEND", raising=False)

    service = vibe_embedded.EmbeddedVibeService()

    assert service.backend_root == Path(backend).resolve()


def test_embedded_vibe_honors_explicit_backend_root(tmp_path, monkeypatch):
    configured = tmp_path / "configured-vibe-backend"
    configured.mkdir()
    monkeypatch.setenv("VIBE_BACKEND_ROOT", str(configured))

    service = vibe_embedded.EmbeddedVibeService()

    assert service.backend_root == configured.resolve()
