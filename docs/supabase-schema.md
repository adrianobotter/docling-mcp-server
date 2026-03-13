# EVIE Supabase Database Schema

Complete reference for all tables, columns, constraints, indexes, RLS policies, triggers, and seed data.

---

## Table Overview

| # | Table | Purpose | HCP Access |
|---|-------|---------|------------|
| 1 | `sponsors` | Pharmaceutical companies sponsoring trials | **Denied** |
| 2 | `trials` | Clinical trial metadata | Read (active + has visible evidence) |
| 3 | `evidence_objects` | Individual data points (endpoints, AEs, subgroups) | Read (published + tier-gated) |
| 4 | `context_envelopes` | Mandatory guardrails attached 1:1 to evidence | Read (follows evidence access) |
| 5 | `hcp_profiles` | Healthcare professional accounts | Read (own row only) |
| 6 | `partner_access_rules` | Sponsor-level tier restrictions per partner | **Denied** |
| 7 | `source_documents` | Raw documents processed by Docling (admin only) | **Denied** |

---

## 1. `sponsors`

Pharmaceutical companies that own and sponsor trials.

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK** | `gen_random_uuid()` |
| `name` | `text` | NOT NULL | — |
| `tier_permissions` | `jsonb` | NOT NULL | `'["tier1"]'` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

**RLS Policy**: `sponsors_deny_hcp` — `USING (false)` — HCPs cannot read.

---

## 2. `trials`

Clinical trial metadata. Trials progress through `draft → active → archived`.

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK** | `gen_random_uuid()` |
| `name` | `text` | NOT NULL | — |
| `drug_name` | `text` | — | — |
| `indication` | `text` | — | — |
| `phase` | `text` | — | — |
| `sponsor_id` | `uuid` | FK → `sponsors(id)` | — |
| `status` | `text` | NOT NULL, CHECK `('draft','active','archived')` | `'draft'` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |
| `updated_at` | `timestamptz` | NOT NULL | `now()` |

**Indexes**:
- `trials_sponsor_id` on `(sponsor_id)`
- `trials_status` on `(status)`

**Trigger**: `trials_updated_at` — auto-sets `updated_at = now()` on UPDATE.

**RLS Policy**: `trials_hcp_select` — HCPs can SELECT trials where:
- `status = 'active'`
- AND at least one published `evidence_object` exists at or below the HCP's `max_tier_access`

---

## 3. `evidence_objects`

Individual clinical data points. The core table of the system.

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK** | `gen_random_uuid()` |
| `trial_id` | `uuid` | NOT NULL, FK → `trials(id)` | — |
| `object_class` | `text` | NOT NULL, CHECK `('primary_endpoint','subgroup','adverse_event','comparator','methodological')` | — |
| `endpoint_name` | `text` | — | — |
| `result_value` | `numeric` | — | — |
| `unit` | `text` | — | — |
| `confidence_interval_low` | `numeric` | — | — |
| `confidence_interval_high` | `numeric` | — | — |
| `p_value` | `numeric` | — | — |
| `time_horizon` | `text` | — | — |
| `subgroup_definition` | `text` | — | — |
| `arm` | `text` | — | — |
| `tier` | `text` | NOT NULL, CHECK `('tier1','tier2','tier3','tier4')` | `'tier1'` |
| `is_published` | `boolean` | NOT NULL | `false` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |
| `search_vector` | `tsvector` | GENERATED ALWAYS AS (full-text of `endpoint_name`, `subgroup_definition`, `arm`) STORED | — |

**Indexes**:
- `evidence_objects_trial_id` on `(trial_id)`
- `evidence_objects_class` on `(object_class)`
- `evidence_objects_tier` on `(tier)`
- `evidence_objects_published` on `(is_published)`
- `evidence_objects_fts` GIN index on `(search_vector)`

**Trigger**: `enforce_envelope_before_publish` — prevents setting `is_published = true` unless a `context_envelope` exists for the evidence object.

**RLS Policy**: `evidence_hcp_select` — HCPs can SELECT where:
- `is_published = true`
- AND `tier_rank(tier) <= tier_rank(hcp.max_tier_access)`

---

## 4. `context_envelopes`

Mandatory context and guardrails attached 1:1 to each evidence object. Every evidence object must have an envelope before it can be published.

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK** | `gen_random_uuid()` |
| `evidence_object_id` | `uuid` | NOT NULL, UNIQUE, FK → `evidence_objects(id)` | — |
| `source_provenance` | `jsonb` | — | — |
| `population_constraints` | `text` | — | — |
| `endpoint_definition` | `text` | — | — |
| `subgroup_qualifiers` | `text` | — | — |
| `interpretation_guardrails` | `text` | NOT NULL | — |
| `safety_statement` | `text` | NOT NULL | — |
| `methodology_qualifiers` | `text` | — | — |
| `generated_at` | `timestamptz` | NOT NULL | `now()` |
| `generated_by` | `text` | NOT NULL | `'cae_auto'` |

**Index**: `context_envelopes_eo_id` on `(evidence_object_id)`

**RLS Policy**: `envelope_hcp_select` — follows `evidence_objects` access. If you can see the evidence object, you see its envelope.

### `source_provenance` JSON Structure

```json
{
  "trial_name": "STEP-4",
  "doi": "10.1001/jama.2021.23619",
  "clinicaltrials_id": "NCT03548935",
  "publication_date": "2022-01-11"
}
```

---

## 5. `hcp_profiles`

Healthcare professional accounts. Links to Supabase Auth (`auth.users`).

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK**, FK → `auth.users(id)` | — |
| `full_name` | `text` | — | — |
| `specialty` | `text` | — | — |
| `npi_number` | `text` | — | — |
| `verification_status` | `text` | NOT NULL, CHECK `('pending','verified','rejected')` | `'pending'` |
| `max_tier_access` | `text` | NOT NULL, CHECK `('tier1','tier2','tier3','tier4')` | `'tier1'` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

**RLS Policy**: `hcp_select_own` — `USING (id = auth.uid())` — users can only read their own row.

---

## 6. `partner_access_rules`

Sponsor-defined tier restrictions for specific partners (e.g., limiting which tiers a partner platform can surface).

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK** | `gen_random_uuid()` |
| `sponsor_id` | `uuid` | NOT NULL, FK → `sponsors(id)` | — |
| `partner_name` | `text` | NOT NULL | — |
| `allowed_tiers` | `text[]` | NOT NULL | `ARRAY['tier1']` |
| `applies_to_indications` | `text[]` | — | — |

**Index**: `partner_access_rules_sponsor` on `(sponsor_id)`

**RLS Policy**: `partner_rules_deny_hcp` — `USING (false)` — HCPs cannot read.

---

## 7. `source_documents`

Raw documents uploaded by sponsors, processed by Docling into structured markdown/tables. Admin-only — never exposed to HCPs via the MCP server.

| Column | Type | Constraints | Default |
|--------|------|-------------|---------|
| `id` | `uuid` | **PK** | `gen_random_uuid()` |
| `trial_id` | `uuid` | NOT NULL, FK → `trials(id)` | — |
| `url` | `text` | — | — |
| `title` | `text` | — | — |
| `docling_markdown` | `text` | — | — |
| `docling_tables` | `jsonb` | — | — |
| `processing_status` | `text` | NOT NULL, CHECK `('pending','complete','failed')` | `'pending'` |
| `created_at` | `timestamptz` | NOT NULL | `now()` |

**Index**: `source_documents_trial_id` on `(trial_id)`

**RLS Policy**: `source_docs_deny_hcp` — `USING (false)` — HCPs cannot read.

---

## Helper Function: `tier_rank()`

Converts tier labels to integers for comparison in RLS policies.

```sql
tier_rank('tier1') → 1
tier_rank('tier2') → 2
tier_rank('tier3') → 3
tier_rank('tier4') → 4
```

Used in RLS policies: `tier_rank(eo.tier) <= tier_rank(hcp.max_tier_access)`

---

## Entity Relationship Diagram

```
auth.users
    │
    └── 1:1 ── hcp_profiles
                    │
                    │ (max_tier_access used by RLS)
                    ▼
sponsors ──1:N── trials ──1:N── evidence_objects ──1:1── context_envelopes
    │                               │
    └──1:N── partner_access_rules   └── search_vector (FTS)
                                    │
trials ──1:N── source_documents     └── tier gating (RLS)
```

---

## Seed Data (STEP-4 Trial)

The `003_seed_step4.sql` migration inserts development data:

| Entity | Count | Details |
|--------|-------|---------|
| Sponsor | 1 | Novo Nordisk (tier1, tier2, tier3) |
| Trial | 1 | STEP-4 — Semaglutide 2.4 mg for Obesity, Phase 3, status=active |
| Evidence Objects | 7 | 2 primary endpoints, 1 subgroup (tier2), 3 adverse events, 1 comparator |
| Context Envelopes | 7 | One per evidence object (all reference DOI 10.1001/jama.2021.23619) |

All evidence objects are published after envelope creation via:
```sql
UPDATE evidence_objects SET is_published = true
WHERE trial_id = 'b0000000-0000-0000-0000-000000000001';
```
