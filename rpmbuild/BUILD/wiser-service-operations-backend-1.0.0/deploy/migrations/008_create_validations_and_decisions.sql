-- Migration 008: Create validation_run and packet_decision tables
-- Purpose: Persist HETS/PECOS validation runs and approve/dismissal decisions
-- Date: 2026-01-05

BEGIN;

-- Ensure pgcrypto extension exists for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- Table: service_ops.validation_run
-- Purpose: Store every HETS and PECOS validation run (request + response + metadata)
-- ============================================================================

CREATE TABLE IF NOT EXISTS service_ops.validation_run (
    validation_run_id BIGSERIAL PRIMARY KEY,
    packet_id BIGINT NOT NULL REFERENCES service_ops.packet(packet_id) ON DELETE CASCADE,
    packet_document_id BIGINT NOT NULL REFERENCES service_ops.packet_document(packet_document_id) ON DELETE CASCADE,
    validation_type TEXT NOT NULL CHECK (validation_type IN ('HETS', 'PECOS')),
    request_payload JSONB NOT NULL,
    response_payload JSONB NULL,
    response_status_code INT NULL,
    response_success BOOLEAN NULL,
    upstream_request_id TEXT NULL,  -- e.g. HETS request_id if present
    normalized_npi TEXT NULL,  -- For PECOS: normalized 10-digit NPI
    duration_ms INT NULL,
    correlation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    created_by TEXT NULL,  -- user email from auth
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE service_ops.validation_run IS 
'Stores every HETS and PECOS validation run with full request/response payloads for audit trail. Request/response may contain PHI (patient MBI, DOB, names).';

COMMENT ON COLUMN service_ops.validation_run.validation_type IS 
'Type of validation: HETS (eligibility) or PECOS (provider enrollment)';

COMMENT ON COLUMN service_ops.validation_run.request_payload IS 
'Full request payload sent to upstream service (JSONB). For HETS: contains patient MBI, DOB, names (PHI). For PECOS: contains NPI.';

COMMENT ON COLUMN service_ops.validation_run.response_payload IS 
'Full response payload from upstream service (JSONB). May contain PHI or sensitive data.';

COMMENT ON COLUMN service_ops.validation_run.correlation_id IS 
'UUID for idempotency and request tracing. Generated server-side.';

COMMENT ON COLUMN service_ops.validation_run.normalized_npi IS 
'For PECOS validations: normalized 10-digit NPI (useful for queries).';

-- Indexes for validation_run
CREATE INDEX IF NOT EXISTS idx_validation_run_doc_time 
ON service_ops.validation_run(packet_document_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_validation_run_packet_time 
ON service_ops.validation_run(packet_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_validation_run_type_doc_time 
ON service_ops.validation_run(validation_type, packet_document_id, created_at DESC);

-- Idempotency index: correlation_id should be unique per validation_type + document
-- Note: correlation_id is UUID, so it's globally unique, but this index helps with idempotency checks
CREATE UNIQUE INDEX IF NOT EXISTS idx_validation_run_idempotency 
ON service_ops.validation_run(validation_type, packet_document_id, correlation_id);

-- Index for querying by correlation_id
CREATE INDEX IF NOT EXISTS idx_validation_run_correlation_id 
ON service_ops.validation_run(correlation_id);

-- ============================================================================
-- Table: service_ops.packet_decision
-- Purpose: Store approve and dismissal decisions with denial reason + details
-- ============================================================================

CREATE TABLE IF NOT EXISTS service_ops.packet_decision (
    packet_decision_id BIGSERIAL PRIMARY KEY,
    packet_id BIGINT NOT NULL REFERENCES service_ops.packet(packet_id) ON DELETE CASCADE,
    packet_document_id BIGINT NOT NULL REFERENCES service_ops.packet_document(packet_document_id) ON DELETE CASCADE,
    decision_type TEXT NOT NULL CHECK (decision_type IN ('APPROVE', 'DISMISSAL')),
    denial_reason TEXT NULL CHECK (denial_reason IN ('MISSING_FIELDS', 'INVALID_PECOS', 'INVALID_HETS', 'PROCEDURE_NOT_SUPPORTED', 'NO_MEDICAL_RECORDS', 'OTHER')),
    denial_details JSONB NULL,  -- reason-specific structure
    notes TEXT NULL,
    linked_validation_run_ids JSONB NULL,  -- { "hets": <id>|null, "pecos": <id>|null }
    correlation_id UUID NOT NULL DEFAULT gen_random_uuid(),
    created_by TEXT NULL,  -- user email from auth
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE service_ops.packet_decision IS 
'Stores approve and dismissal decisions for packets/documents. Links to last validation runs for audit trail.';

COMMENT ON COLUMN service_ops.packet_decision.decision_type IS 
'Type of decision: APPROVE or DISMISSAL';

COMMENT ON COLUMN service_ops.packet_decision.denial_reason IS 
'For DISMISSAL decisions: reason code (MISSING_FIELDS, INVALID_PECOS, INVALID_HETS, PROCEDURE_NOT_SUPPORTED, NO_MEDICAL_RECORDS, OTHER)';

COMMENT ON COLUMN service_ops.packet_decision.denial_details IS 
'For DISMISSAL decisions: reason-specific structured data (JSONB). Structure varies by denial_reason.';

COMMENT ON COLUMN service_ops.packet_decision.linked_validation_run_ids IS 
'JSONB object with references to last validation runs: { "hets": <validation_run_id>|null, "pecos": <validation_run_id>|null }';

COMMENT ON COLUMN service_ops.packet_decision.correlation_id IS 
'UUID for idempotency and request tracing. Generated server-side.';

-- Indexes for packet_decision
CREATE INDEX IF NOT EXISTS idx_packet_decision_doc_time 
ON service_ops.packet_decision(packet_document_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_packet_decision_packet_time 
ON service_ops.packet_decision(packet_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_packet_decision_type_doc 
ON service_ops.packet_decision(decision_type, packet_document_id);

-- Idempotency index: correlation_id should be unique per decision_type + document
CREATE UNIQUE INDEX IF NOT EXISTS idx_packet_decision_idempotency 
ON service_ops.packet_decision(decision_type, packet_document_id, correlation_id);

-- Index for querying by correlation_id
CREATE INDEX IF NOT EXISTS idx_packet_decision_correlation_id 
ON service_ops.packet_decision(correlation_id);

-- GIN index for JSONB queries on denial_details
CREATE INDEX IF NOT EXISTS idx_packet_decision_denial_details 
ON service_ops.packet_decision USING GIN (denial_details);

-- GIN index for JSONB queries on linked_validation_run_ids
CREATE INDEX IF NOT EXISTS idx_packet_decision_linked_runs 
ON service_ops.packet_decision USING GIN (linked_validation_run_ids);

COMMIT;

-- ============================================================================
-- Verification Queries (optional - run manually to verify)
-- ============================================================================

-- Verify tables exist
-- SELECT table_name, table_schema
-- FROM information_schema.tables
-- WHERE table_schema = 'service_ops'
-- AND table_name IN ('validation_run', 'packet_decision');

-- Verify columns
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_schema = 'service_ops'
-- AND table_name IN ('validation_run', 'packet_decision')
-- ORDER BY table_name, ordinal_position;

-- Verify indexes
-- SELECT tablename, indexname, indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'service_ops'
-- AND tablename IN ('validation_run', 'packet_decision')
-- ORDER BY tablename, indexname;

-- Verify constraints
-- SELECT conname, contype, pg_get_constraintdef(oid)
-- FROM pg_constraint
-- WHERE connamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'service_ops')
-- AND conrelid IN (
--     SELECT oid FROM pg_class WHERE relname IN ('validation_run', 'packet_decision')
-- )
-- ORDER BY conname;

