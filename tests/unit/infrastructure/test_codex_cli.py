from unittest.mock import AsyncMock

import pytest

from src.infrastructure.ai.codex_cli import (
    _probe_runtime_home,
    codex_cli_status,
    invoke_codex_cli,
    resolve_codex_cli,
    resolve_codex_home,
)


class _FakeProcess:
    def __init__(self, stdout: bytes, returncode: int = 0, stderr: bytes = b""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.payload = b""
        self.killed = False

    async def communicate(self, payload: bytes):
        self.payload = payload
        return self.stdout, self.stderr

    def kill(self):
        self.killed = True


def test_resolve_codex_cli_prefers_packaged_native_binary(monkeypatch, tmp_path):
    shim = tmp_path / "codex.cmd"
    shim.write_text("@echo off", encoding="utf-8")
    native = (
        tmp_path
        / "node_modules"
        / "@openai"
        / "codex"
        / "node_modules"
        / "@openai"
        / "codex-win32-x64"
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "bin"
        / "codex.exe"
    )
    native.parent.mkdir(parents=True)
    native.write_bytes(b"native")
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.shutil.which",
        lambda value: str(shim),
    )

    assert resolve_codex_cli("codex") == str(native)


def test_resolve_codex_home_from_cli_user_profile(monkeypatch, tmp_path):
    service_home = tmp_path / "service-profile"
    user_home = tmp_path / "user-profile"
    executable = user_home / ".npm-global" / "vendor" / "codex.exe"
    auth_file = user_home / ".codex" / "auth.json"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native")
    auth_file.parent.mkdir(parents=True)
    auth_file.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.Path.home",
        lambda: service_home,
    )

    assert resolve_codex_home(str(executable)) == user_home / ".codex"


def test_codex_cli_status_probes_runtime_write_access(monkeypatch, tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_cli",
        lambda configured_path: "codex.exe",
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_home",
        lambda executable: codex_home,
    )

    status = codex_cli_status()

    assert status["runtime_writable"] is True
    assert status["runtime_error"] == ""


def test_runtime_probe_fails_after_one_permission_error(monkeypatch, tmp_path):
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    calls = 0

    def deny_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise PermissionError(13, "access denied")

    monkeypatch.setattr("src.infrastructure.ai.codex_cli.os.open", deny_once)

    writable, error = _probe_runtime_home(codex_home)

    assert writable is False
    assert "PermissionError" in error
    assert calls == 1


@pytest.mark.asyncio
async def test_invoke_codex_cli_is_ephemeral_read_only_and_sanitizes_secrets(
    monkeypatch, tmp_path,
):
    stdout = (
        b'{"type":"item.completed","item":{"type":"agent_message",'
        b'"text":"review ok"}}\n'
        b'{"type":"turn.completed"}\n'
    )
    process = _FakeProcess(stdout)
    create = AsyncMock(return_value=process)
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_cli",
        lambda configured_path: "codex.exe",
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_home",
        lambda executable: tmp_path / ".codex",
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.asyncio.create_subprocess_exec",
        create,
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-leak")

    result = await invoke_codex_cli(
        "facts",
        "rules",
        model="gpt-5.6-terra",
        reasoning_effort="low",
    )

    assert result == "review ok"
    args = create.await_args.args
    kwargs = create.await_args.kwargs
    assert "--ephemeral" in args
    assert "--ignore-user-config" in args
    assert "--ignore-rules" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("--model") + 1] == "gpt-5.6-terra"
    assert "DEEPSEEK_API_KEY" not in kwargs["env"]
    assert kwargs["env"]["CODEX_HOME"] == str(tmp_path / ".codex")
    assert "禁止调用工具" in process.payload.decode("utf-8")


@pytest.mark.asyncio
async def test_invoke_codex_cli_rejects_missing_final_message(monkeypatch, tmp_path):
    process = _FakeProcess(b'{"type":"turn.completed"}\n')
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_cli",
        lambda configured_path: "codex.exe",
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_home",
        lambda executable: tmp_path,
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )

    with pytest.raises(RuntimeError, match="no final agent message"):
        await invoke_codex_cli("facts", model="gpt-5.6-terra")


@pytest.mark.asyncio
async def test_invoke_codex_cli_surfaces_stderr_failure(monkeypatch, tmp_path):
    process = _FakeProcess(
        b"",
        returncode=1,
        stderr=b"Error: failed to initialize app-server client: access denied\n",
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_cli",
        lambda configured_path: "codex.exe",
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.resolve_codex_home",
        lambda executable: tmp_path,
    )
    monkeypatch.setattr(
        "src.infrastructure.ai.codex_cli.asyncio.create_subprocess_exec",
        AsyncMock(return_value=process),
    )

    with pytest.raises(RuntimeError, match="access denied"):
        await invoke_codex_cli("facts", model="gpt-5.6-terra")
