"""Tests for EVIE database layer — row-to-model converters."""

from src.evie.db import _row_to_evidence_object, _row_to_envelope, _pair_evidence_with_envelope


class TestRowToEvidenceObject:
    def test_full_row(self, sample_evidence_row):
        eo = _row_to_evidence_object(sample_evidence_row)
        assert eo.id == "eo-001"
        assert eo.object_class == "primary_endpoint"
        assert eo.result_value == -15.2
        assert eo.confidence_interval == [-16.1, -14.3]
        assert eo.p_value == 0.0001

    def test_null_confidence_interval(self, sample_evidence_row):
        sample_evidence_row["confidence_interval_low"] = None
        sample_evidence_row["confidence_interval_high"] = None
        eo = _row_to_evidence_object(sample_evidence_row)
        assert eo.confidence_interval is None

    def test_null_result_value(self, sample_evidence_row):
        sample_evidence_row["result_value"] = None
        eo = _row_to_evidence_object(sample_evidence_row)
        assert eo.result_value is None

    def test_null_p_value(self, sample_evidence_row):
        sample_evidence_row["p_value"] = None
        eo = _row_to_evidence_object(sample_evidence_row)
        assert eo.p_value is None


class TestRowToEnvelope:
    def test_full_envelope(self, sample_envelope_row):
        env = _row_to_envelope(sample_envelope_row)
        assert env.safety_statement == "Common adverse events include nausea, vomiting, diarrhea."
        assert env.interpretation_guardrails == "Results apply to the mITT population."
        assert env.source_provenance is not None
        assert env.source_provenance.trial_name == "STEP-4"

    def test_string_provenance_ignored(self, sample_envelope_row):
        sample_envelope_row["source_provenance"] = "not a dict"
        env = _row_to_envelope(sample_envelope_row)
        assert env.source_provenance is None

    def test_null_optional_fields(self, sample_envelope_row):
        sample_envelope_row["population_constraints"] = None
        sample_envelope_row["endpoint_definition"] = None
        sample_envelope_row["source_provenance"] = None
        env = _row_to_envelope(sample_envelope_row)
        assert env.population_constraints is None
        assert env.source_provenance is None


class TestPairEvidenceWithEnvelope:
    def test_valid_pair(self, sample_evidence_row, sample_envelope_row):
        pair = _pair_evidence_with_envelope(sample_evidence_row, sample_envelope_row)
        assert pair is not None
        assert pair.evidence_object.id == "eo-001"
        assert pair.context_envelope.safety_statement is not None

    def test_missing_envelope_returns_none(self, sample_evidence_row):
        pair = _pair_evidence_with_envelope(sample_evidence_row, None)
        assert pair is None
