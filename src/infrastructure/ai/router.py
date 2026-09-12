"""Codex-first AI router with an explicit legacy DeepSeek compatibility path."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from config.settings import settings
from src.infrastructure.ai.codex_cli import (
    CodexCLIError,
    codex_cli_status,
    invoke_codex_cli,
)


class AIProviderError(RuntimeError):
    """An AI provider returned a non-fallback error."""


class AIFallbackEligibleError(AIProviderError):
    """A provider failure that permits a configured compatibility fallback."""


@dataclass(frozen=True)
class AIResponse:
    text: str
    provider: str
    model: str
    fallback_used: bool = False
    fallback_reason: str | None = None


class AIRouter:
    """Route scheduled stock research through the configured primary provider."""

    @staticmethod
    def _usable_key(value: str | None) -> bool:
        normalized = str(value or "").strip().lower()
        return bool(normalized) and not any(
            marker in normalized
            for marker in ("your-key", "placeholder", "change-me", "example")
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        allow_fallback: bool = False,
        deepseek_attempts: int | None = None,
        primary_provider: str | None = None,
    ) -> AIResponse:
        provider = str(primary_provider or settings.AI_PRIMARY_PROVIDER).strip().lower()
        if provider == "codex_cli":
            return await self._generate_codex_cli_first(
                prompt,
                system_prompt,
                allow_fallback=allow_fallback,
                deepseek_attempts=deepseek_attempts,
            )
        if provider != "deepseek":
            raise AIProviderError(f"Unsupported AI primary provider: {provider}")
        return await self._generate_deepseek_first(
            prompt,
            system_prompt,
            allow_fallback=allow_fallback,
            deepseek_attempts=deepseek_attempts,
        )

    async def _generate_deepseek_first(
        self,
        prompt: str,
        system_prompt: str,
        *,
        allow_fallback: bool,
        deepseek_attempts: int | None,
    ) -> AIResponse:
        if not settings.DEEPSEEK_API_KEY:
            raise AIProviderError("DEEPSEEK_API_KEY is not configured; DeepSeek cannot be called")
        attempts = max(
            1,
            int(deepseek_attempts or settings.AI_NETWORK_RETRY_ATTEMPTS),
        )
        primary_error: AIFallbackEligibleError | None = None
        for attempt in range(1, attempts + 1):
            try:
                text = await self._call_deepseek(prompt, system_prompt)
                return AIResponse(text=text, provider="deepseek", model=settings.DEEPSEEK_MODEL)
            except AIFallbackEligibleError as exc:
                primary_error = exc
                if attempt < attempts:
                    await asyncio.sleep(min(2.0, 0.5 * attempt))
        assert primary_error is not None
        if not allow_fallback:
            raise AIProviderError(
                f"DeepSeek unavailable after {attempts} attempt(s): {primary_error}"
            ) from primary_error

        cli = codex_cli_status(settings.CODEX_CLI_PATH)
        cli_error = "not configured"
        if (
            cli["executable_found"]
            and cli["auth_file_present"]
            and cli.get("runtime_writable")
        ):
            try:
                text = await invoke_codex_cli(
                    prompt,
                    system_prompt,
                    configured_path=settings.CODEX_CLI_PATH,
                    model=settings.CODEX_MODEL,
                    reasoning_effort=settings.CODEX_REASONING_EFFORT,
                    timeout_seconds=settings.CODEX_TIMEOUT_SECONDS,
                    max_output_tokens=settings.CODEX_MAX_OUTPUT_TOKENS,
                )
                return AIResponse(
                    text=text,
                    provider="codex_cli",
                    model=settings.CODEX_MODEL,
                    fallback_used=True,
                    fallback_reason=str(primary_error),
                )
            except CodexCLIError as exc:
                cli_error = str(exc)

        if self._usable_key(settings.OPENAI_API_KEY):
            try:
                text = await self._call_codex(prompt, system_prompt)
            except AIProviderError as fallback_error:
                raise AIProviderError(
                    f"DeepSeek unavailable ({primary_error}); Codex CLI fallback failed "
                    f"({cli_error}); direct API fallback failed ({fallback_error})"
                ) from fallback_error
            return AIResponse(
                text=text,
                provider="codex",
                model=settings.CODEX_MODEL,
                fallback_used=True,
                fallback_reason=str(primary_error),
            )

        raise AIProviderError(
            f"DeepSeek unavailable ({primary_error}); Codex CLI fallback failed "
            f"({cli_error}); direct API fallback is not configured"
        ) from primary_error

    async def _generate_codex_cli_first(
        self,
        prompt: str,
        system_prompt: str,
        *,
        allow_fallback: bool,
        deepseek_attempts: int | None,
    ) -> AIResponse:
        try:
            text = await invoke_codex_cli(
                prompt,
                system_prompt,
                configured_path=settings.CODEX_CLI_PATH,
                model=settings.CODEX_MODEL,
                reasoning_effort=settings.CODEX_REASONING_EFFORT,
                timeout_seconds=settings.CODEX_TIMEOUT_SECONDS,
                max_output_tokens=settings.CODEX_MAX_OUTPUT_TOKENS,
            )
            return AIResponse(
                text=text,
                provider="codex_cli",
                model=settings.CODEX_MODEL,
            )
        except CodexCLIError as primary_error:
            # The scheduled stock loop is Codex-only. Keep the historical
            # keyword arguments for callers, but never silently switch a
            # Codex run to a different provider after a CLI failure.
            raise AIProviderError(f"Codex CLI unavailable: {primary_error}") from primary_error

    async def _call_codex(self, prompt: str, system_prompt: str) -> str:
        payload: dict[str, Any] = {
            "model": settings.CODEX_MODEL,
            "input": prompt,
            "max_output_tokens": settings.CODEX_MAX_OUTPUT_TOKENS,
        }
        if system_prompt:
            payload["instructions"] = system_prompt
        try:
            async with httpx.AsyncClient(
                timeout=self._http_timeout(settings.CODEX_TIMEOUT_SECONDS),
                follow_redirects=True,
            ) as client:
                response = await client.post(
                    f"{settings.OPENAI_BASE_URL.rstrip('/')}/responses",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise AIFallbackEligibleError(
                "no response: "
                f"{type(exc).__name__} endpoint={self._endpoint(settings.OPENAI_BASE_URL)}"
            ) from exc
        if response.status_code == 429:
            raise AIFallbackEligibleError("quota or rate limit (HTTP 429)")
        if response.status_code >= 500:
            raise AIFallbackEligibleError(f"provider no response (HTTP {response.status_code})")
        if response.is_error:
            raise AIProviderError(f"Codex request failed with HTTP {response.status_code}")
        data = response.json()
        text = data.get("output_text") or self._extract_response_text(data)
        if not text:
            raise AIFallbackEligibleError("empty response")
        return str(text)

    async def _call_deepseek(self, prompt: str, system_prompt: str) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        try:
            async with httpx.AsyncClient(
                timeout=self._http_timeout(settings.CODEX_TIMEOUT_SECONDS),
                follow_redirects=True,
            ) as client:
                response = await client.post(
                    f"{settings.DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                    json={
                        "model": settings.DEEPSEEK_MODEL,
                        "messages": messages,
                        "max_tokens": settings.DEEPSEEK_MAX_TOKENS,
                        "temperature": settings.DEEPSEEK_TEMPERATURE,
                    },
                )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise AIFallbackEligibleError(
                "no response: "
                f"{type(exc).__name__} endpoint={self._endpoint(settings.DEEPSEEK_BASE_URL)}"
            ) from exc
        if response.status_code == 429:
            raise AIFallbackEligibleError("quota or rate limit (HTTP 429)")
        if response.status_code >= 500:
            raise AIFallbackEligibleError(f"provider no response (HTTP {response.status_code})")
        if response.is_error:
            raise AIProviderError(f"DeepSeek request failed with HTTP {response.status_code}")
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIFallbackEligibleError("DeepSeek returned an invalid response") from exc
        if not text:
            raise AIFallbackEligibleError("DeepSeek returned an empty response")
        return str(text)

    @staticmethod
    def _extract_response_text(data: dict[str, Any]) -> str:
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    chunks.append(str(content["text"]))
        return "\n".join(chunks)

    def status(self) -> dict[str, Any]:
        cli = codex_cli_status(settings.CODEX_CLI_PATH)
        cli_configured = bool(
            cli["executable_found"]
            and cli["auth_file_present"]
            and cli.get("runtime_writable")
        )
        primary_is_codex = settings.AI_PRIMARY_PROVIDER == "codex_cli"
        return {
            "primary": settings.AI_PRIMARY_PROVIDER,
            "primary_model": (
                settings.CODEX_MODEL if primary_is_codex else settings.DEEPSEEK_MODEL
            ),
            "primary_configured": (
                cli_configured
                if primary_is_codex
                else self._usable_key(settings.DEEPSEEK_API_KEY)
            ),
            "review_provider": settings.AI_REVIEW_PROVIDER,
            "review_model": settings.CODEX_MODEL,
            "review_configured": cli_configured,
            "codex_cli": cli,
            "fallback": "disabled" if primary_is_codex else "codex_cli",
            "fallback_model": "" if primary_is_codex else settings.CODEX_MODEL,
            "fallback_configured": False if primary_is_codex else cli_configured,
            "direct_api_fallback_configured": self._usable_key(settings.OPENAI_API_KEY),
            "fallback_policy": [
                "timeout", "network_error", "empty_response", "http_429", "http_5xx"
            ],
            "deepseek_base_url": self._endpoint(settings.DEEPSEEK_BASE_URL),
            "network_retry_attempts": settings.AI_NETWORK_RETRY_ATTEMPTS,
        }

    @staticmethod
    def _endpoint(url: str) -> str:
        """Return a safe endpoint label without exposing credentials or paths."""
        parsed = urlparse(str(url or ""))
        if not parsed.hostname:
            return "unknown"
        return f"{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"

    @staticmethod
    def _http_timeout(seconds: float) -> httpx.Timeout:
        total = max(5.0, float(seconds))
        return httpx.Timeout(
            connect=min(12.0, total),
            read=total,
            write=min(20.0, total),
            pool=min(12.0, total),
        )


ai_router = AIRouter()
