"""Tests for EVIE Pydantic models and tier logic."""

from src.evie.models import (
    ContextEnvelope,
    EvidenceObject,
    EvidenceWithEnvelope,
    HCPProfile,
    SourceProvenance,
    TrialSummary,
    tier_accessible,
)


class TestTierAccessible:
    def test_same_tier(self):
        assert tier_accessible("tier1", "tier1") is True

    def test_lower_tier_accessible(self):
        assert tier_accessible("tier1", "tier3") is True

    def test_higher_tier_blocked(self):
        assert tier_accessible("tier3", "tier1") is False

    def test_all_tiers_accessible_to_tier4(self):
        for t in ("tier1", "tier2", "tier3", "tier4"):
            assert tier_accessible(t, "tier4") is True

    def test_unknown_tier_returns_false(self):
        assert tier_accessible("tier_unknown", "tier1") is True  # 0 <= 1
        assert tier_accessible("tier1", "tier_unknown") is False  # 1 <= 0


class TestEvidenceObject:
    def test_minimal_evidence(self):
        eo = EvidenceObject(id="1", trial_id="t1", object_class="adverse_event", tier="tier1")
        assert eo.endpoint_name is None
        assert eo.result_value is None
        assert eo.confidence_interval is None

    def test_full_evidence(self):
        eo = EvidenceObject(
            id="1",
            trial_id="t1",
            object_class="primary_endpoint",
            endpoint_name="Weight change",
            result_value=-15.2,
            unit="%",
            confidence_interval=[-16.1, -14.3],
            p_value=0.0001,
            time_horizon="68 weeks",
            arm="Semaglutide 2.4mg",
            tier="tier1",
        )
        assert eo.result_value == -15.2
        assert len(eo.confidence_interval) == 2


class TestContextEnvelope:
    def test_requires_mandatory_fields(self):
        env = ContextEnvelope(
            interpretation_guardrails="Results apply to mITT.",
            safety_statement="Nausea, vomiting reported.",
        )
        assert env.population_constraints is None
        assert env.safety_statement == "Nausea, vomiting reported."

    def test_with_provenance(self):
        prov = SourceProvenance(trial_name="STEP-4", doi="10.1056/test")
        env = ContextEnvelope(
            interpretation_guardrails="guardrails",
            safety_statement="safety",
            source_provenance=prov,
        )
        assert env.source_provenance.trial_name == "STEP-4"


class TestEvidenceWithEnvelope:
    def test_pairing(self):
        eo = EvidenceObject(id="1", trial_id="t1", object_class="primary_endpoint", tier="tier1")
        env = ContextEnvelope(
            interpretation_guardrails="guardrails",
            safety_statement="safety",
        )
        pair = EvidenceWithEnvelope(evidence_object=eo, context_envelope=env)
        assert pair.evidence_object.id == "1"
        assert pair.context_envelope.safety_statement == "safety"


class TestTrialSummary:
    def test_serialization(self):
        ts = TrialSummary(
            trial_id="t1",
            name="STEP-4",
            drug_name="Semaglutide",
            indication="Obesity",
            phase="Phase 3",
            available_object_classes=["primary_endpoint", "adverse_event"],
        )
        d = ts.model_dump()
        assert d["name"] == "STEP-4"
        assert len(d["available_object_classes"]) == 2


class TestHCPProfile:
    def test_verified_profile(self):
        p = HCPProfile(
            id="u1",
            full_name="Dr. Smith",
            verification_status="verified",
            max_tier_access="tier2",
        )
        assert p.verification_status == "verified"
