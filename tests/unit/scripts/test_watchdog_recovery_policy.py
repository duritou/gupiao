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
    @(500, 900, $true, 50, 0, 'wait'),
    @(600, 900, $true, 50, 0, 'restart'),
    @(90, 400, $false, 9, 1, 'restart'),
    @(600, 900, $true, 50, 2, 'circuit_open')
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


def test_pytest_singleton_uses_isolated_storage():
    from src.infrastructure.storage.market_database import market_db

    assert market_db.db_path.parent.name.startswith("adaptive-pytest-")
    assert market_db.db_path.resolve() != (
        Path(__file__).resolve().parents[3] / "src/infrastructure/storage/market_data.db"
    ).resolve()
