from unittest.mock import AsyncMock

import pytest

from src.infrastructure.ai.codex_cli import CodexCLIError
from src.infrastructure.ai.router import AIFallbackEligibleError, AIProviderError, AIRouter


@pytest.mark.asyncio
async def test_codex_is_default_primary(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.AI_PRIMARY_PROVIDER", "codex_cli")
    codex = AsyncMock(return_value="codex result")
    deepseek = AsyncMock(return_value="deepseek result")
    monkeypatch.setattr("src.infrastructure.ai.router.invoke_codex_cli", codex)
    monkeypatch.setattr(router, "_call_deepseek", deepseek)
    result = await router.generate("analyze")
    assert result.provider == "codex_cli"
    assert result.fallback_used is False
    codex.assert_awaited_once()
    deepseek.assert_not_awaited()


@pytest.mark.asyncio
async def test_falls_back_to_direct_api_when_codex_cli_is_unavailable(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr("src.infrastructure.ai.router.settings.OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "src.infrastructure.ai.router.codex_cli_status",
        lambda configured_path: {"executable_found": False, "auth_file_present": False},
    )
    monkeypatch.setattr(
        router, "_call_deepseek",
        AsyncMock(side_effect=AIFallbackEligibleError("quota or rate limit (HTTP 429)")),
    )
    monkeypatch.setattr(router, "_call_codex", AsyncMock(return_value="fallback"))
    result = await router.generate(
        "analyze", primary_provider="deepseek", allow_fallback=True
    )
    assert result.provider == "codex"
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_deepseek_empty_response_falls_back_to_codex_cli(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr("src.infrastructure.ai.router.settings.OPENAI_API_KEY", None)
    monkeypatch.setattr(
        "src.infrastructure.ai.router.codex_cli_status",
        lambda configured_path: {
            "executable_found": True,
            "auth_file_present": True,
            "runtime_writable": True,
        },
    )
    monkeypatch.setattr(
        router,
        "_call_deepseek",
        AsyncMock(side_effect=AIFallbackEligibleError("DeepSeek returned an empty response")),
    )
    cli = AsyncMock(return_value="codex preselection")
    monkeypatch.setattr("src.infrastructure.ai.router.invoke_codex_cli", cli)

    result = await router.generate(
        "analyze", primary_provider="deepseek", allow_fallback=True,
        deepseek_attempts=1,
    )

    assert result.provider == "codex_cli"
    assert result.fallback_used is True
    assert "empty response" in str(result.fallback_reason)
    cli.assert_awaited_once()


@pytest.mark.asyncio
async def test_does_not_fallback_for_deepseek_auth_or_bad_request(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr("src.infrastructure.ai.router.settings.OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        router, "_call_deepseek", AsyncMock(side_effect=AIProviderError("HTTP 401"))
    )
    fallback = AsyncMock(return_value="fallback")
    monkeypatch.setattr(router, "_call_codex", fallback)
    with pytest.raises(AIProviderError, match="401"):
        await router.generate("analyze", primary_provider="deepseek")
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_deepseek_only_mode_retries_and_never_calls_codex(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    primary = AsyncMock(side_effect=[
        AIFallbackEligibleError("no response: timeout"),
        "deepseek recovered",
    ])
    fallback = AsyncMock(return_value="codex")
    monkeypatch.setattr(router, "_call_deepseek", primary)
    monkeypatch.setattr(router, "_call_codex", fallback)

    result = await router.generate(
        "review",
        allow_fallback=False,
        deepseek_attempts=2,
        primary_provider="deepseek",
    )

    assert result.provider == "deepseek"
    assert primary.await_count == 2
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_placeholder_codex_key_is_not_used(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr(
        "src.infrastructure.ai.router.settings.OPENAI_API_KEY", "sk-your-key-here"
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.router.codex_cli_status",
        lambda configured_path: {"executable_found": False, "auth_file_present": False},
    )
    monkeypatch.setattr(
        router,
        "_call_deepseek",
        AsyncMock(side_effect=AIFallbackEligibleError("quota or rate limit (HTTP 429)")),
    )
    fallback = AsyncMock(return_value="fallback")
    monkeypatch.setattr(router, "_call_codex", fallback)

    with pytest.raises(AIProviderError, match="direct API fallback is not configured"):
        await router.generate(
            "analyze", primary_provider="deepseek", allow_fallback=True
        )
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_fallback_failure_preserves_primary_reason(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr("src.infrastructure.ai.router.settings.OPENAI_API_KEY", "sk-real-test")
    monkeypatch.setattr(
        "src.infrastructure.ai.router.codex_cli_status",
        lambda configured_path: {"executable_found": False, "auth_file_present": False},
    )
    monkeypatch.setattr(
        router,
        "_call_deepseek",
        AsyncMock(side_effect=AIFallbackEligibleError("no response: timeout")),
    )
    monkeypatch.setattr(
        router,
        "_call_codex",
        AsyncMock(side_effect=AIProviderError("Codex request failed with HTTP 401")),
    )

    with pytest.raises(
        AIProviderError,
        match="DeepSeek unavailable.*direct API fallback failed",
    ):
        await router.generate(
            "analyze", primary_provider="deepseek", allow_fallback=True
        )


@pytest.mark.asyncio
async def test_codex_cli_can_be_selected_as_review_primary(monkeypatch):
    router = AIRouter()
    cli = AsyncMock(return_value="codex review")
    deepseek = AsyncMock(return_value="deepseek fallback")
    monkeypatch.setattr("src.infrastructure.ai.router.invoke_codex_cli", cli)
    monkeypatch.setattr(router, "_call_deepseek", deepseek)

    result = await router.generate("review", primary_provider="codex_cli")

    assert result.provider == "codex_cli"
    assert result.model == "gpt-5.6-terra"
    assert result.fallback_used is False
    cli.assert_awaited_once()
    deepseek.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_cli_failure_is_fail_closed_even_when_fallback_requested(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", "test")
    deepseek = AsyncMock(return_value="fallback")
    monkeypatch.setattr(
        "src.infrastructure.ai.router.invoke_codex_cli",
        AsyncMock(side_effect=CodexCLIError("session expired")),
    )
    monkeypatch.setattr(router, "_call_deepseek", deepseek)

    with pytest.raises(AIProviderError, match="Codex CLI unavailable"):
        await router.generate(
            "review",
            primary_provider="codex_cli",
            allow_fallback=True,
            deepseek_attempts=1,
        )

    deepseek.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_cli_failure_without_fallback_is_explicit(monkeypatch):
    router = AIRouter()
    monkeypatch.setattr("src.infrastructure.ai.router.settings.DEEPSEEK_API_KEY", None)
    monkeypatch.setattr(
        "src.infrastructure.ai.router.invoke_codex_cli",
        AsyncMock(side_effect=CodexCLIError("not logged in")),
    )

    with pytest.raises(AIProviderError, match="Codex CLI unavailable"):
        await router.generate("review", primary_provider="codex_cli")
