-- ============================================================================
-- UNIFIED MIGRATION SCRIPT: ServiceOps Workflow Implementation
-- Combines migrations 017-022 into one idempotent script
-- Handles current production state (partially applied migration 018)
-- Date: 2026-01-XX
-- ============================================================================
-- 
-- This script consolidates:
-- - Migration 017: New Workflow Schema
-- - Migration 018: Create send_integration table (handles existing table)
-- - Migration 019: Update ClinicalOps watermark (creates table if missing)
-- - Migration 020: Fix timezone columns (safe conversion)
-- - Migration 021: Complete send_integration structure
-- - Migration 022: Add json_sent_to_integration flag
--
-- IMPORTANT: This script is idempotent and safe to run multiple times.
-- ============================================================================

BEGIN;

-- ============================================================================
-- SECTION 1: Migration 017 - New Workflow Schema
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1.1 Add validation_status to packet table
-- ----------------------------------------------------------------------------

ALTER TABLE service_ops.packet
ADD COLUMN IF NOT EXISTS validation_status TEXT;

-- Set default for existing rows
UPDATE service_ops.packet
SET validation_status = 'Pending - Validation'
WHERE validation_status IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet
ALTER COLUMN validation_status SET DEFAULT 'Pending - Validation';

-- Only set NOT NULL if not already set (idempotent)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND column_name = 'validation_status'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE service_ops.packet
        ALTER COLUMN validation_status SET NOT NULL;
    END IF;
END $$;

COMMENT ON COLUMN service_ops.packet.validation_status IS 
    'Validation status: Pending - Validation, Validation In Progress, Pending - Manual Review, Validation Updated, Validation Complete, Validation Failed';

-- Add CHECK constraint for validation_status
ALTER TABLE service_ops.packet
DROP CONSTRAINT IF EXISTS check_validation_status;

ALTER TABLE service_ops.packet
ADD CONSTRAINT check_validation_status 
CHECK (validation_status IN (
    'Pending - Validation',
    'Validation In Progress',
    'Pending - Manual Review',
    'Validation Updated',
    'Validation Complete',
    'Validation Failed'
));

-- ----------------------------------------------------------------------------
-- 1.2 Update detailed_status to be NOT NULL with default
-- ----------------------------------------------------------------------------

-- Set default for existing NULL rows
UPDATE service_ops.packet
SET detailed_status = 'Pending - New'
WHERE detailed_status IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet
ALTER COLUMN detailed_status SET DEFAULT 'Pending - New';

-- Only set NOT NULL if not already set (idempotent)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND column_name = 'detailed_status'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE service_ops.packet
        ALTER COLUMN detailed_status SET NOT NULL;
    END IF;
END $$;

-- Add CHECK constraint for detailed_status
ALTER TABLE service_ops.packet
DROP CONSTRAINT IF EXISTS check_detailed_status;

ALTER TABLE service_ops.packet
ADD CONSTRAINT check_detailed_status 
CHECK (detailed_status IN (
    'Pending - New',
    'Intake',
    'Validation',
    'Pending - Clinical Review',
    'Clinical Decision Received',
    'Pending - UTN',
    'UTN Received',
    'Generate Decision Letter - Pending',
    'Generate Decision Letter - Complete',
    'Send Decision Letter - Pending',
    'Send Decision Letter - Complete',
    'Decision Complete',
    'Dismissal',
    'Dismissal Complete'
));

-- ----------------------------------------------------------------------------
-- 1.3 Add operational_decision and clinical_decision to packet_decision
-- ----------------------------------------------------------------------------

-- Add operational_decision
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS operational_decision TEXT;

-- Set default for existing rows
UPDATE service_ops.packet_decision
SET operational_decision = 'PENDING'
WHERE operational_decision IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet_decision
ALTER COLUMN operational_decision SET DEFAULT 'PENDING';

-- Only set NOT NULL if not already set (idempotent)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND column_name = 'operational_decision'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE service_ops.packet_decision
        ALTER COLUMN operational_decision SET NOT NULL;
    END IF;
END $$;

COMMENT ON COLUMN service_ops.packet_decision.operational_decision IS 
    'Operational decision: PENDING, DISMISSAL, DISMISSAL_COMPLETE, DECISION_COMPLETE';

-- Add CHECK constraint for operational_decision
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_operational_decision;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_operational_decision 
CHECK (operational_decision IN ('PENDING', 'DISMISSAL', 'DISMISSAL_COMPLETE', 'DECISION_COMPLETE'));

-- Add clinical_decision
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS clinical_decision TEXT;

-- Set default for existing rows
UPDATE service_ops.packet_decision
SET clinical_decision = 'PENDING'
WHERE clinical_decision IS NULL;

-- Make NOT NULL with default
ALTER TABLE service_ops.packet_decision
ALTER COLUMN clinical_decision SET DEFAULT 'PENDING';

-- Only set NOT NULL if not already set (idempotent)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND column_name = 'clinical_decision'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE service_ops.packet_decision
        ALTER COLUMN clinical_decision SET NOT NULL;
    END IF;
END $$;

COMMENT ON COLUMN service_ops.packet_decision.clinical_decision IS 
    'Clinical decision: PENDING, AFFIRM, NON_AFFIRM';

-- Add CHECK constraint for clinical_decision
ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_clinical_decision;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_clinical_decision 
CHECK (clinical_decision IN ('PENDING', 'AFFIRM', 'NON_AFFIRM'));

-- ----------------------------------------------------------------------------
-- 1.4 Add audit trail fields to packet_decision
-- ----------------------------------------------------------------------------

-- Add is_active
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- Set default for existing rows
UPDATE service_ops.packet_decision
SET is_active = TRUE
WHERE is_active IS NULL;

-- Make NOT NULL
ALTER TABLE service_ops.packet_decision
ALTER COLUMN is_active SET DEFAULT TRUE;

-- Only set NOT NULL if not already set (idempotent)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND column_name = 'is_active'
          AND is_nullable = 'YES'
    ) THEN
        ALTER TABLE service_ops.packet_decision
        ALTER COLUMN is_active SET NOT NULL;
    END IF;
END $$;

COMMENT ON COLUMN service_ops.packet_decision.is_active IS 
    'TRUE for current active decision, FALSE for historical/superseded decisions';

-- Add supersedes (FK to previous decision)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS supersedes BIGINT;

-- Add foreign key constraint if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND constraint_name = 'fk_packet_decision_supersedes'
    ) THEN
        ALTER TABLE service_ops.packet_decision
        ADD CONSTRAINT fk_packet_decision_supersedes 
        FOREIGN KEY (supersedes) 
        REFERENCES service_ops.packet_decision(packet_decision_id) 
        ON DELETE SET NULL;
    END IF;
END $$;

COMMENT ON COLUMN service_ops.packet_decision.supersedes IS 
    'FK to packet_decision_id that this decision supersedes (for audit trail)';

-- Add superseded_by (FK to next decision)
ALTER TABLE service_ops.packet_decision
ADD COLUMN IF NOT EXISTS superseded_by BIGINT;

-- Add foreign key constraint if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND constraint_name = 'fk_packet_decision_superseded_by'
    ) THEN
        ALTER TABLE service_ops.packet_decision
        ADD CONSTRAINT fk_packet_decision_superseded_by 
        FOREIGN KEY (superseded_by) 
        REFERENCES service_ops.packet_decision(packet_decision_id) 
        ON DELETE SET NULL;
    END IF;
END $$;

COMMENT ON COLUMN service_ops.packet_decision.superseded_by IS 
    'FK to packet_decision_id that supersedes this decision (for audit trail)';

-- Add index for active decisions
CREATE INDEX IF NOT EXISTS idx_packet_decision_active 
ON service_ops.packet_decision(packet_id, is_active) 
WHERE is_active = TRUE;

-- ----------------------------------------------------------------------------
-- 1.5 Create packet_validation table for validation audit trail
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS service_ops.packet_validation (
    packet_validation_id BIGSERIAL PRIMARY KEY,
    packet_id BIGINT NOT NULL REFERENCES service_ops.packet(packet_id) ON DELETE CASCADE,
    packet_document_id BIGINT NOT NULL REFERENCES service_ops.packet_document(packet_document_id) ON DELETE CASCADE,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'Pending - Validation',
        'Validation In Progress',
        'Pending - Manual Review',
        'Validation Updated',
        'Validation Complete',
        'Validation Failed'
    )),
    validation_type TEXT,  -- 'HETS', 'PECOS', 'FIELD_VALIDATION', 'MANUAL_REVIEW', 'FINAL'
    validation_result JSONB,  -- Validation output data
    validation_errors JSONB,  -- Any errors found
    is_passed BOOLEAN,  -- TRUE if validation passed
    is_active BOOLEAN NOT NULL DEFAULT TRUE,  -- TRUE for current validation state
    supersedes BIGINT REFERENCES service_ops.packet_validation(packet_validation_id) ON DELETE SET NULL,
    superseded_by BIGINT REFERENCES service_ops.packet_validation(packet_validation_id) ON DELETE SET NULL,
    update_reason TEXT,  -- Why validation was updated/corrected
    validated_by TEXT,  -- User who performed/updated validation
    validated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE service_ops.packet_validation IS 
    'Audit trail of all validation updates. New record for each validation change.';

COMMENT ON COLUMN service_ops.packet_validation.validation_status IS 
    'Validation status at time of this record';

COMMENT ON COLUMN service_ops.packet_validation.validation_type IS 
    'Type of validation: HETS, PECOS, FIELD_VALIDATION, MANUAL_REVIEW, FINAL';

COMMENT ON COLUMN service_ops.packet_validation.is_active IS 
    'TRUE for current validation state, FALSE for historical';

-- Indexes for packet_validation
CREATE INDEX IF NOT EXISTS idx_packet_validation_packet_active 
ON service_ops.packet_validation(packet_id, is_active) 
WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_packet_validation_doc_time 
ON service_ops.packet_validation(packet_document_id, validated_at DESC);

CREATE INDEX IF NOT EXISTS idx_packet_validation_packet_time 
ON service_ops.packet_validation(packet_id, validated_at DESC);

-- ----------------------------------------------------------------------------
-- 1.6 Update letter_status CHECK constraint
-- ----------------------------------------------------------------------------

ALTER TABLE service_ops.packet_decision
DROP CONSTRAINT IF EXISTS check_letter_status;

ALTER TABLE service_ops.packet_decision
ADD CONSTRAINT check_letter_status 
CHECK (letter_status IS NULL OR letter_status IN ('NONE', 'PENDING', 'READY', 'FAILED', 'SENT'));

-- ============================================================================
-- SECTION 2: Migration 018 - Create send_integration table (handle existing)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 2.1 Create send_integration table if it doesn't exist
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS service_ops.send_integration (
    message_id BIGSERIAL PRIMARY KEY,
    decision_tracking_id UUID NOT NULL,
    workflow_instance_id BIGINT,
    payload JSONB NOT NULL,
    message_status_id INTEGER,
    correlation_id UUID,
    attempt_count INTEGER DEFAULT 1,
    resend_of_message_id BIGINT,
    payload_hash TEXT,
    payload_version INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ,
    audit_user VARCHAR(100),
    audit_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT false
);

-- ----------------------------------------------------------------------------
-- 2.2 Add missing columns if table already exists (idempotent)
-- ----------------------------------------------------------------------------

-- Add correlation_id if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'correlation_id'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN correlation_id UUID;
    END IF;
END $$;

-- Add attempt_count if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'attempt_count'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN attempt_count INTEGER DEFAULT 1;
    END IF;
END $$;

-- Add resend_of_message_id if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'resend_of_message_id'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN resend_of_message_id BIGINT;
    END IF;
END $$;

-- Add payload_hash if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'payload_hash'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN payload_hash TEXT;
    END IF;
END $$;

-- Add payload_version if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'payload_version'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN payload_version INTEGER DEFAULT 1;
    END IF;
END $$;

-- Add updated_at if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN updated_at TIMESTAMPTZ;
    END IF;
END $$;

-- Ensure workflow_instance_id exists (might be missing if table was created manually)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'send_integration' 
          AND column_name = 'workflow_instance_id'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD COLUMN workflow_instance_id BIGINT;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 2.3 Add foreign key constraints (idempotent)
-- ----------------------------------------------------------------------------

-- Add fk_send_integration_message_status if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'service_ops'
          AND table_name = 'send_integration'
          AND constraint_name = 'fk_send_integration_message_status'
    ) THEN
        -- Only add FK if message_status table exists
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'message_status'
        ) THEN
            ALTER TABLE service_ops.send_integration
            ADD CONSTRAINT fk_send_integration_message_status 
            FOREIGN KEY (message_status_id) 
            REFERENCES service_ops.message_status(message_status_id);
        END IF;
    END IF;
END $$;

-- Add fk_send_integration_workflow_instance if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'service_ops'
          AND table_name = 'send_integration'
          AND constraint_name = 'fk_send_integration_workflow_instance'
    ) THEN
        -- Only add FK if workflow_instance table exists
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'workflow_instance'
        ) THEN
            ALTER TABLE service_ops.send_integration
            ADD CONSTRAINT fk_send_integration_workflow_instance 
            FOREIGN KEY (workflow_instance_id) 
            REFERENCES service_ops.workflow_instance(workflow_instance_id);
        END IF;
    END IF;
END $$;

-- Add fk_send_integration_resend if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_schema = 'service_ops'
          AND table_name = 'send_integration'
          AND constraint_name = 'fk_send_integration_resend'
    ) THEN
        ALTER TABLE service_ops.send_integration
        ADD CONSTRAINT fk_send_integration_resend 
        FOREIGN KEY (resend_of_message_id) 
        REFERENCES service_ops.send_integration(message_id) 
        ON DELETE SET NULL;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 2.4 Add comments
-- ----------------------------------------------------------------------------

COMMENT ON TABLE service_ops.send_integration IS 
    'ServiceOps → Integration outbox. Stores ESMD payloads and letter packages for Integration service to consume.';

COMMENT ON COLUMN service_ops.send_integration.message_id IS 
    'Primary key, auto-incrementing message ID';

COMMENT ON COLUMN service_ops.send_integration.decision_tracking_id IS 
    'UUID linking to service_ops.packet.decision_tracking_id';

COMMENT ON COLUMN service_ops.send_integration.payload IS 
    'JSONB payload containing message_type (ESMD_PAYLOAD or LETTER_PACKAGE) and full message data';

COMMENT ON COLUMN service_ops.send_integration.message_status_id IS 
    'FK to service_ops.message_status. Status: 1=INGESTED, 2=VALIDATED, 3=SENT, 4=ERROR';

COMMENT ON COLUMN service_ops.send_integration.correlation_id IS 
    'UUID for tracking resends and correlating multiple requests per decision_tracking_id';

COMMENT ON COLUMN service_ops.send_integration.attempt_count IS 
    'Number of attempts (1 = initial send, 2+ = resends after UTN_FAIL)';

COMMENT ON COLUMN service_ops.send_integration.resend_of_message_id IS 
    'FK to previous message_id if this is a resend (NULL for initial send)';

COMMENT ON COLUMN service_ops.send_integration.payload_hash IS 
    'SHA-256 hash of payload for audit and deduplication';

COMMENT ON COLUMN service_ops.send_integration.payload_version IS 
    'Payload version number (1 = initial, 2+ = updated payload on resend)';

-- ----------------------------------------------------------------------------
-- 2.5 Create indexes (idempotent)
-- ----------------------------------------------------------------------------

-- Decision tracking lookup
CREATE INDEX IF NOT EXISTS idx_send_integration_decision_tracking 
    ON service_ops.send_integration(decision_tracking_id);

-- Status filtering
CREATE INDEX IF NOT EXISTS idx_send_integration_message_status 
    ON service_ops.send_integration(message_status_id) 
    WHERE message_status_id IS NOT NULL;

-- Correlation ID (for resend tracking)
CREATE INDEX IF NOT EXISTS idx_send_integration_correlation_id 
    ON service_ops.send_integration(correlation_id) 
    WHERE correlation_id IS NOT NULL;

-- Resend chain
CREATE INDEX IF NOT EXISTS idx_send_integration_resend 
    ON service_ops.send_integration(resend_of_message_id) 
    WHERE resend_of_message_id IS NOT NULL;

-- Attempt count (for retry queries)
CREATE INDEX IF NOT EXISTS idx_send_integration_attempt_count 
    ON service_ops.send_integration(attempt_count) 
    WHERE attempt_count > 1;

-- Composite: decision_tracking_id + attempt_count
CREATE INDEX IF NOT EXISTS idx_send_integration_decision_attempt 
    ON service_ops.send_integration(decision_tracking_id, attempt_count);

-- Created at (for polling)
CREATE INDEX IF NOT EXISTS idx_send_integration_created_at 
    ON service_ops.send_integration(created_at);

-- Payload GIN index (for JSONB queries)
CREATE INDEX IF NOT EXISTS idx_send_integration_payload_gin 
    ON service_ops.send_integration USING GIN (payload);

-- Message type in payload (for filtering)
CREATE INDEX IF NOT EXISTS idx_send_integration_message_type 
    ON service_ops.send_integration((payload->>'message_type')) 
    WHERE payload->>'message_type' IS NOT NULL;

-- ============================================================================
-- SECTION 3: Migration 019 - Update ClinicalOps watermark (create if missing)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 3.1 Create clinical_ops_poll_watermark table if it doesn't exist
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS service_ops.clinical_ops_poll_watermark (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_created_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00',
    last_message_id BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT check_single_row CHECK (id = 1)
);

COMMENT ON TABLE service_ops.clinical_ops_poll_watermark IS 
    'Tracks last processed message_id from service_ops.send_serviceops for ClinicalOps inbox polling';

COMMENT ON COLUMN service_ops.clinical_ops_poll_watermark.last_created_at IS 
    'Last processed created_at timestamp from service_ops.send_serviceops (same strategy as integration inbox)';

COMMENT ON COLUMN service_ops.clinical_ops_poll_watermark.last_message_id IS 
    'Last processed message_id from service_ops.send_serviceops (same strategy as integration inbox)';

-- Initialize with default value (UTC epoch) if table was just created
INSERT INTO service_ops.clinical_ops_poll_watermark (id, last_created_at, last_message_id, updated_at)
VALUES (1, '1970-01-01 00:00:00+00', 0, CURRENT_TIMESTAMP)
ON CONFLICT (id) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 3.2 Add last_created_at column if it doesn't exist
-- ----------------------------------------------------------------------------

ALTER TABLE service_ops.clinical_ops_poll_watermark
ADD COLUMN IF NOT EXISTS last_created_at TIMESTAMPTZ NOT NULL DEFAULT '1970-01-01 00:00:00+00';

-- If column already exists as TIMESTAMP (without timezone), convert it
DO $$
BEGIN
    -- Check if column exists and is TIMESTAMP (not TIMESTAMPTZ)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_schema = 'service_ops' 
          AND table_name = 'clinical_ops_poll_watermark' 
          AND column_name = 'last_created_at'
          AND data_type = 'timestamp without time zone'
    ) THEN
        -- Convert TIMESTAMP to TIMESTAMPTZ (assumes existing values are UTC)
        ALTER TABLE service_ops.clinical_ops_poll_watermark
        ALTER COLUMN last_created_at TYPE TIMESTAMPTZ USING last_created_at AT TIME ZONE 'UTC';
    END IF;
END $$;

-- Update existing records to have epoch timestamp if last_created_at is NULL or invalid
UPDATE service_ops.clinical_ops_poll_watermark
SET last_created_at = '1970-01-01 00:00:00+00'
WHERE id = 1 AND (last_created_at IS NULL OR last_created_at < '1970-01-01 00:00:00+00');

-- ============================================================================
-- SECTION 4: Migration 020 - Fix timezone columns (safe conversion)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 4.1 Fix service_ops.send_serviceops.created_at
-- ----------------------------------------------------------------------------

DO $$
BEGIN
    -- Check if table and column exist
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'send_serviceops'
          AND column_name = 'created_at'
    ) THEN
        -- Check if column is TIMESTAMP (not TIMESTAMPTZ)
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_serviceops'
              AND column_name = 'created_at'
              AND data_type = 'timestamp without time zone'
        ) THEN
            -- Convert TIMESTAMP to TIMESTAMPTZ (assumes existing values are UTC)
            ALTER TABLE service_ops.send_serviceops
            ALTER COLUMN created_at TYPE TIMESTAMPTZ 
            USING created_at AT TIME ZONE 'UTC';
        END IF;
    END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 4.2 Fix service_ops.integration_poll_watermark.last_created_at
-- ----------------------------------------------------------------------------

DO $$
BEGIN
    -- Check if table and column exist
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'integration_poll_watermark'
          AND column_name = 'last_created_at'
    ) THEN
        -- Check if column is TIMESTAMP (not TIMESTAMPTZ)
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'integration_poll_watermark'
              AND column_name = 'last_created_at'
              AND data_type = 'timestamp without time zone'
        ) THEN
            -- Convert TIMESTAMP to TIMESTAMPTZ (assumes existing values are UTC)
            ALTER TABLE service_ops.integration_poll_watermark
            ALTER COLUMN last_created_at TYPE TIMESTAMPTZ 
            USING last_created_at AT TIME ZONE 'UTC';
        END IF;
    END IF;
END $$;

-- ============================================================================
-- SECTION 5: Migration 021 - Complete send_integration structure
-- (Most columns already added in Section 2, but ensure all are present)
-- ============================================================================

-- This section is mostly redundant with Section 2, but ensures all columns
-- from migration 021 are present. The DO blocks in Section 2 already handle
-- adding missing columns, so this section just adds the correlation_id index
-- that migration 021 creates.

-- Create correlation_id index if it doesn't exist (from migration 021)
CREATE INDEX IF NOT EXISTS idx_send_integration_correlation_id 
    ON service_ops.send_integration(correlation_id) 
    WHERE correlation_id IS NOT NULL;

-- ============================================================================
-- SECTION 6: Migration 022 - Add json_sent_to_integration flag
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 6.1 Add json_sent_to_integration column
-- ----------------------------------------------------------------------------

-- Add column to track if JSON was sent to integration
-- DEFAULT NULL ensures old records (non-generated payloads) are correctly marked as NULL
ALTER TABLE service_ops.send_serviceops
ADD COLUMN IF NOT EXISTS json_sent_to_integration BOOLEAN DEFAULT NULL;

-- Safety: If column was previously added with DEFAULT FALSE, update old records to NULL
-- This handles the case where migration was run before with incorrect default
DO $$
BEGIN
    -- Only run UPDATE if send_integration table exists (migration 018 was run)
    -- This ensures we don't accidentally update legitimate FALSE values from JSON Generator
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'service_ops' AND table_name = 'send_integration'
    ) THEN
        -- Update FALSE values that existed before send_integration table was created
        -- These are old records that should be NULL
        UPDATE service_ops.send_serviceops
        SET json_sent_to_integration = NULL
        WHERE json_sent_to_integration = FALSE
          AND created_at < COALESCE(
              (SELECT MIN(created_at) 
               FROM service_ops.send_integration 
               WHERE created_at IS NOT NULL),
              CURRENT_TIMESTAMP
          );
    END IF;
END $$;

COMMENT ON COLUMN service_ops.send_serviceops.json_sent_to_integration IS 
    'Indicates if the generated JSON payload was successfully sent to send_integration table. NULL = not a generated payload, TRUE = sent successfully, FALSE = failed to send.';

-- ----------------------------------------------------------------------------
-- 6.2 Create index for faster lookups
-- ----------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_send_serviceops_json_sent 
ON service_ops.send_serviceops(decision_tracking_id, json_sent_to_integration)
WHERE json_sent_to_integration IS NOT NULL;

COMMENT ON INDEX service_ops.idx_send_serviceops_json_sent IS 
    'Index for querying generated payloads by decision_tracking_id and send status.';

-- ============================================================================
-- COMMIT TRANSACTION
-- ============================================================================

COMMIT;

-- ============================================================================
-- VERIFICATION QUERIES (Run after migration to verify success)
-- ============================================================================

-- Uncomment to run verification queries:
/*
-- Verify packet table changes
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'packet'
  AND column_name IN ('validation_status', 'detailed_status')
ORDER BY column_name;

-- Verify packet_decision table changes
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'packet_decision'
  AND column_name IN ('operational_decision', 'clinical_decision', 'is_active', 'supersedes', 'superseded_by')
ORDER BY column_name;

-- Verify packet_validation table exists
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_validation'
        ) THEN 'EXISTS'
        ELSE 'MISSING'
    END AS packet_validation_status;

-- Verify send_integration table structure
SELECT 
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_integration'
ORDER BY ordinal_position;

-- Verify send_serviceops.json_sent_to_integration
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_serviceops'
  AND column_name = 'json_sent_to_integration';

-- Verify clinical_ops_poll_watermark.last_created_at
SELECT 
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'clinical_ops_poll_watermark'
  AND column_name = 'last_created_at';

-- Verify timezone conversions
SELECT 
    table_name,
    column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND (
    (table_name = 'send_serviceops' AND column_name = 'created_at')
    OR (table_name = 'integration_poll_watermark' AND column_name = 'last_created_at')
  );

SELECT 'Unified migration 017-022 completed successfully' AS status;
*/

