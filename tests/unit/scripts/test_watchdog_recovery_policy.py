import shutil
import subprocess
from pathlib import Path

import pytest


def test_watchdog_recovery_policy_without_starting_services():
    shell = shutil.which("powershell")
    if not shell:
        pytest.skip("Windows PowerShell required")
    launcher = Path(__file__).resolve().parents[4] / "scripts/start_adaptive_learning_backend.ps1"
    command = r"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__PATH__', [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$fn = $ast.Find({param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Get-HealthRecoveryDecision'
}, $true)
Invoke-Expression $fn.Extent.Text
$cases = @(
    @(60, 60, $false, 9, 0, 'wait'),
    @(90, 400, $false, 2, 0, 'wait'),
    @(119, 900, $true, 50, 0, 'wait'),
    @(120, 900, $true, 50, 0, 'restart'),
    @(90, 400, $false, 9, 1, 'restart'),
    @(600, 900, $true, 50, 2, 'cooldown_restart')
)
foreach ($case in $cases) {
    $actual = Get-HealthRecoveryDecision $case[0] $case[1] $case[2] $case[3] $case[4]
    if ($actual -ne $case[5]) { throw "Expected $($case[5]), got $actual" }
}
""".replace("__PATH__", str(launcher).replace("'", "''"))
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_watchdog_consumes_valid_restart_request(tmp_path):
    shell = shutil.which("powershell")
    if not shell:
        pytest.skip("Windows PowerShell required")
    launcher = Path(__file__).resolve().parents[4] / "scripts/start_adaptive_learning_backend.ps1"
    request_path = tmp_path / "restart-request.json"
    request_path.write_text(
        '{"action":"restart","request_id":"test-request"}', encoding="utf-8"
    )
    command = r"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__LAUNCHER__', [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$fn = $ast.Find({param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Consume-RestartRequest'
}, $true)
Invoke-Expression $fn.Extent.Text
$RestartRequestPath = '__REQUEST__'
function Write-StartupLog([string]$Message) { }
if (-not (Consume-RestartRequest)) { throw 'valid restart request was rejected' }
if (Test-Path -LiteralPath $RestartRequestPath) { throw 'restart request was not consumed' }
""".replace("__LAUNCHER__", str(launcher).replace("'", "''")).replace(
        "__REQUEST__", str(request_path).replace("'", "''")
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_watchdog_uses_exclusive_single_instance_lock():
    launcher = Path(__file__).resolve().parents[4] / "scripts/start_adaptive_learning_backend.ps1"
    source = launcher.read_text(encoding="utf-8-sig")

    assert "runtime\\watchdog.lock" in source
    assert "[IO.FileShare]::None" in source
    assert "duplicate launcher exiting" in source


def test_pytest_singleton_uses_isolated_storage():
    from src.infrastructure.storage.market_database import market_db

    assert market_db.db_path.parent.name.startswith("adaptive-pytest-")
    assert market_db.db_path.resolve() != (
        Path(__file__).resolve().parents[3] / "src/infrastructure/storage/market_data.db"
    ).resolve()


def test_deployer_accepts_protected_managed_process_only_during_recovery():
    shell = shutil.which("powershell")
    if not shell:
        pytest.skip("Windows PowerShell required")
    deployer = Path(__file__).resolve().parents[3] / "scripts/deploy_research_backend.ps1"
    command = r"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '__PATH__', [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($name in @('Assert-ExpectedApi', 'Get-VerifiedWatchdogAncestors')) {
    $fn = $ast.Find({param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $name
    }, $true)
    Invoke-Expression $fn.Extent.Text
}
$script:records = @{
    10 = [pscustomobject]@{ ProcessId=10; ParentProcessId=20; Name='python.exe'; CommandLine=$null }
    20 = [pscustomobject]@{ ProcessId=20; ParentProcessId=30; Name='python.exe'; CommandLine=$null }
    30 = [pscustomobject]@{ ProcessId=30; ParentProcessId=40; Name='powershell.exe'; CommandLine=$null }
    40 = [pscustomobject]@{ ProcessId=40; ParentProcessId=0; Name='svchost.exe'; CommandLine=$null }
}
function Get-ProcessRecord([int]$ProcessId) { return $script:records[$ProcessId] }
$RecoverUnresponsive = $true
Assert-ExpectedApi $script:records[10]
$RecoverUnresponsive = $false
$rejected = $false
try { Assert-ExpectedApi $script:records[10] } catch { $rejected = $true }
if (-not $rejected) { throw 'protected process was accepted without recovery authorization' }
$explicit = [pscustomobject]@{
    ProcessId=50; ParentProcessId=0; Name='python.exe'; CommandLine='python scripts/run_api.py'
}
Assert-ExpectedApi $explicit
""".replace("__PATH__", str(deployer).replace("'", "''"))
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
