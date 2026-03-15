"""Shared fixtures for EVIE MCP Server tests."""

import os
import pytest

# Set required env vars before any EVIE module imports
os.environ.setdefault("SUPABASE_URL", "https://test-project.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")


@pytest.fixture
def sample_hcp_row():
    return {
        "id": "user-123",
        "full_name": "Dr. Jane Smith",
        "specialty": "Endocrinology",
        "verification_status": "verified",
        "max_tier_access": "tier2",
    }


@pytest.fixture
def sample_evidence_row():
    return {
        "id": "eo-001",
        "trial_id": "trial-001",
        "object_class": "primary_endpoint",
        "endpoint_name": "Body weight change from baseline",
        "result_value": -15.2,
        "unit": "%",
        "confidence_interval_low": -16.1,
        "confidence_interval_high": -14.3,
        "p_value": 0.0001,
        "time_horizon": "68 weeks",
        "subgroup_definition": None,
        "arm": "Semaglutide 2.4mg",
        "tier": "tier1",
    }


@pytest.fixture
def sample_envelope_row():
    return {
        "id": "env-001",
        "evidence_object_id": "eo-001",
        "population_constraints": "Adults with BMI >= 30",
        "endpoint_definition": "Percentage change in body weight from randomization to week 68",
        "subgroup_qualifiers": None,
        "interpretation_guardrails": "Results apply to the mITT population.",
        "safety_statement": "Common adverse events include nausea, vomiting, diarrhea.",
        "methodology_qualifiers": None,
        "source_provenance": {
            "trial_name": "STEP-4",
            "doi": "10.1056/NEJMoa2032183",
            "clinicaltrials_id": "NCT03548987",
            "publication_date": "2021-03-18",
        },
    }
