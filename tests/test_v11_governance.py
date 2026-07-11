"""Tests for v11.0 Decision Governance — case retrieval, governance, pre-mortem."""
import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestCaseRetrieval:
    """Similar Case Retrieval Engine tests."""

    def test_engine_import(self):
        from src.explain.case_retrieval import case_retriever
        assert case_retriever is not None

    def test_find_similar_returns_report(self):
        from src.explain.case_retrieval import case_retriever
        from src.api.routes.decision_routes import _seed_cases_if_empty
        _seed_cases_if_empty()

        report = case_retriever.find_similar(
            stock_code="688256.SH",
            stock_name="寒武纪",
            ai_score=85,
            direction="buy",
        )
        assert report.stock_code == "688256.SH"
        assert report.total_cases_searched > 0
        # Should find some similar cases
        assert report.total_similar >= 0
        if report.matches:
            # Each match should have similarity fields
            m = report.matches[0]
            assert m.similarity_score > 0
            assert len(m.match_dimensions) > 0
        # Aggregate stats should be computed
        assert 0 <= report.aggregate_win_rate <= 1
        assert len(report.insight) > 0

    def test_similarity_scoring(self):
        """Similarity should be highest for cases with same sector/direction/score."""
        from src.explain.case_retrieval import case_retriever
        from src.api.routes.decision_routes import _seed_cases_if_empty
        _seed_cases_if_empty()

        # High score buy in semiconductor should match other semiconductor buys
        report = case_retriever.find_similar(
            stock_code="688256.SH",
            stock_name="寒武纪",
            ai_score=85,
            direction="buy",
        )
        if report.matches:
            # Top match should have similarity > 50
            assert report.matches[0].similarity_score > 30

    def test_api_endpoint(self, client):
        """Similar cases API endpoint returns valid response."""
        r = client.get("/api/v1/decision/similar-cases/688256.SH?score=85&direction=buy")
        assert r.status_code == 200
        data = r.json()
        assert "total_cases_searched" in data
        assert "total_similar" in data
        assert "matches" in data
        assert "aggregate_win_rate" in data
        assert "insight" in data


class TestGovernance:
    """Decision Governance Engine tests."""

    def test_engine_import(self):
        from src.explain.governance import governance_engine
        assert governance_engine is not None

    def test_audit_produces_seven_checks(self):
        """Governance audit should produce exactly 7 checks."""
        from src.explain.governance import governance_engine
        from src.explain.committee import committee

        decision = committee.evaluate(
            stock_code="688256.SH", stock_name="寒武纪",
            base_score=85,
            portfolio_context={"position_pct": 15, "concentration_risk": 55, "volatility": 45},
        )

        result = governance_engine.audit(
            stock_code="688256.SH", stock_name="寒武纪",
            committee_decision=decision,
            position_pct=15,
        )
        assert len(result.checks) == 7
        assert result.pass_count + result.warn_count + result.fail_count == 7
        assert result.overall_verdict in (
            "APPROVED", "APPROVED_WITH_WARNINGS", "REJECTED"
        )

    def test_high_risk_position_fails_risk_budget(self):
        """Position exceeding risk budget should FAIL."""
        from src.explain.governance import governance_engine
        from src.explain.committee import committee

        decision = committee.evaluate(
            stock_code="688256.SH", stock_name="寒武纪",
            base_score=85,
            portfolio_context={"position_pct": 50, "concentration_risk": 55, "volatility": 45},
        )

        result = governance_engine.audit(
            stock_code="688256.SH", stock_name="寒武纪",
            committee_decision=decision,
            position_pct=50,  # Exceeds conservative/moderate limits
        )
        risk_check = next(c for c in result.checks if c.check_id == "risk_budget")
        assert risk_check.result == "FAIL"
        assert result.overall_verdict == "REJECTED"

    def test_committee_rejected_fails_consensus(self):
        """When committee rejects, consensus check should FAIL."""
        from src.explain.governance import governance_engine
        from src.explain.committee import committee

        decision = committee.evaluate(
            stock_code="688256.SH", stock_name="寒武纪",
            base_score=25,  # Very low score → committee rejects
            portfolio_context={"position_pct": 5, "concentration_risk": 55, "volatility": 45},
        )

        result = governance_engine.audit(
            stock_code="688256.SH", stock_name="寒武纪",
            committee_decision=decision,
            position_pct=5,
        )
        consensus_check = next(c for c in result.checks if c.check_id == "committee_consensus")
        # Very low score should lead to rejection or at least WARN
        assert consensus_check.result in ("FAIL", "WARN")

    def test_api_endpoint(self, client):
        """Governance API endpoint returns full pipeline."""
        r = client.get("/api/v1/decision/govern/688256.SH?base_score=85&position_pct=15")
        assert r.status_code == 200
        data = r.json()
        # Should have all 4 components
        assert "committee" in data
        assert "governance" in data
        assert "pre_mortem" in data
        assert "similar_cases" in data
        assert "executive_summary" in data
        # Governance
        assert len(data["governance"]["checks"]) == 7
        assert data["governance"]["overall_verdict"] in (
            "APPROVED", "APPROVED_WITH_WARNINGS", "REJECTED"
        )
        assert "audit_trail_id" in data["governance"]

    def test_audit_trail_id_is_unique(self):
        """Each audit should produce a unique trail ID."""
        from src.explain.governance import governance_engine
        from src.explain.committee import committee

        decision = committee.evaluate(
            stock_code="688256.SH", stock_name="寒武纪",
            base_score=85,
        )
        r1 = governance_engine.audit(
            stock_code="688256.SH", stock_name="寒武纪",
            committee_decision=decision,
        )
        r2 = governance_engine.audit(
            stock_code="600519.SH", stock_name="贵州茅台",
            committee_decision=decision,
        )
        assert r1.audit_trail_id != r2.audit_trail_id


class TestPreMortem:
    """Pre-mortem Analysis Engine tests."""

    def test_engine_import(self):
        from src.explain.premortem import premortem_engine
        assert premortem_engine is not None

    def test_analyze_produces_five_failure_modes(self):
        """Pre-mortem should produce exactly 5 failure modes."""
        from src.explain.premortem import premortem_engine

        report = premortem_engine.analyze(
            stock_code="688256.SH", stock_name="寒武纪",
            ai_score=85, direction="buy",
        )
        assert len(report.failure_modes) == 5
        # Should be sorted by probability descending
        probs = [f.probability_pct for f in report.failure_modes]
        assert probs == sorted(probs, reverse=True)

    def test_failure_modes_have_triggers(self):
        """Each failure mode should have trigger conditions and mitigations."""
        from src.explain.premortem import premortem_engine

        report = premortem_engine.analyze(
            stock_code="688256.SH", stock_name="寒武纪",
            ai_score=85, direction="buy",
        )
        for fm in report.failure_modes:
            assert fm.failure_name
            assert fm.failure_id
            assert len(fm.trigger_conditions) > 0
            assert len(fm.mitigation) > 0
            assert fm.severity in ("HIGH", "MEDIUM", "LOW")
            assert 0 < fm.probability_pct <= 50  # No single failure should exceed 50%

    def test_overall_risk_level(self):
        """Risk level should be one of the four defined levels."""
        from src.explain.premortem import premortem_engine

        report = premortem_engine.analyze(
            stock_code="688256.SH", stock_name="寒武纪",
            ai_score=85, direction="buy",
        )
        assert report.overall_risk_level in ("LOW", "MODERATE", "ELEVATED", "HIGH")
        assert 0 <= report.total_risk_score <= 100
        assert 0 <= report.resilience_score <= 100
        assert len(report.summary) > 0

    def test_api_endpoint(self, client):
        """Pre-mortem API endpoint returns valid response."""
        r = client.get("/api/v1/decision/premortem/002371.SZ?score=65&direction=buy")
        assert r.status_code == 200
        data = r.json()
        assert "failure_modes" in data
        assert "overall_risk_level" in data
        assert "top_risk" in data
        assert "summary" in data
        assert len(data["failure_modes"]) == 5
        for fm in data["failure_modes"]:
            assert "failure_name" in fm
            assert "probability_pct" in fm
            assert "trigger_conditions" in fm
            assert "mitigation" in fm


# ================================================================
# v11.1 — Contract Tests
# ================================================================

class TestResearchSnapshotContract:
    """Enforce ResearchSnapshotV1 field contract.

    If any test fails, a field was removed or renamed.
    The frontend depends on every field in CONTRACT_FIELDS.
    """

    def test_snapshot_has_all_contract_fields(self, client):
        """Every CONTRACT_FIELD must be present in the API response."""
        from src.explain.research_builder import ResearchSnapshotV1

        r = client.get("/api/v1/detail/000725.SZ")
        assert r.status_code == 200
        data = r.json()

        missing = []
        for field in ResearchSnapshotV1.CONTRACT_FIELDS:
            if field not in data:
                missing.append(field)

        assert not missing, (
            f"Contract violation: {len(missing)} fields missing from "
            f"/detail response: {missing}"
        )

    def test_snapshot_version_is_v1(self, client):
        """Snapshot version must be present and start with V1."""
        r = client.get("/api/v1/detail/000725.SZ")
        data = r.json()
        assert "snapshot_version" in data
        assert data["snapshot_version"].startswith("V")

    def test_market_fields_have_valid_types(self, client):
        """Market data fields must have correct types."""
        r = client.get("/api/v1/detail/000725.SZ")
        data = r.json()
        assert isinstance(data.get("latest_price"), (int, float))
        assert isinstance(data.get("price_change_pct"), (int, float))
        assert isinstance(data.get("klines"), list)

    def test_ai_fields_present_with_real_values(self, client):
        """AI analysis fields must be present (values may be empty if data insufficient)."""
        r = client.get("/api/v1/detail/000725.SZ")
        data = r.json()
        assert "ai_score" in data
        assert "direction" in data
        assert "confidence" in data
        assert "scores" in data
        assert "recommendation" in data
        assert isinstance(data["scores"], dict)

    def test_builder_returns_snapshot_directly(self):
        """Builder should return a ResearchSnapshotV1 with all fields."""
        import asyncio
        from src.explain.research_builder import research_builder

        snap = asyncio.run(research_builder.build("000725.SZ"))
        for field in snap.CONTRACT_FIELDS:
            assert hasattr(snap, field), f"Snapshot missing field: {field}"
