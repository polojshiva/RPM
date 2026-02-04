-- ============================================================================
-- VERIFICATION SCRIPT: Unified Migration 017-022
-- Run this after executing UNIFIED_MIGRATION_017_022.sql
-- ============================================================================

-- ============================================================================
-- SECTION 1: Verify Migration 017 - New Workflow Schema
-- ============================================================================

-- 1.1 Verify packet.validation_status
SELECT 
    'packet.validation_status' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet'
              AND column_name = 'validation_status'
              AND is_nullable = 'NO'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    (SELECT data_type FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'packet'
       AND column_name = 'validation_status') AS data_type,
    (SELECT column_default FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'packet'
       AND column_name = 'validation_status') AS default_value;

-- 1.2 Verify packet.validation_status constraint
SELECT 
    'packet.check_validation_status' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.check_constraints
            WHERE constraint_schema = 'service_ops'
              AND constraint_name = 'check_validation_status'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.3 Verify packet.detailed_status
SELECT 
    'packet.detailed_status' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet'
              AND column_name = 'detailed_status'
              AND is_nullable = 'NO'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    (SELECT data_type FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'packet'
       AND column_name = 'detailed_status') AS data_type;

-- 1.4 Verify packet.detailed_status constraint
SELECT 
    'packet.check_detailed_status' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.check_constraints
            WHERE constraint_schema = 'service_ops'
              AND constraint_name = 'check_detailed_status'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.5 Verify packet_decision.operational_decision
SELECT 
    'packet_decision.operational_decision' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_decision'
              AND column_name = 'operational_decision'
              AND is_nullable = 'NO'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.6 Verify packet_decision.clinical_decision
SELECT 
    'packet_decision.clinical_decision' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_decision'
              AND column_name = 'clinical_decision'
              AND is_nullable = 'NO'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.7 Verify packet_decision.is_active
SELECT 
    'packet_decision.is_active' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_decision'
              AND column_name = 'is_active'
              AND is_nullable = 'NO'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.8 Verify packet_decision.supersedes and superseded_by
SELECT 
    'packet_decision.supersedes' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_decision'
              AND column_name = 'supersedes'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

SELECT 
    'packet_decision.superseded_by' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_decision'
              AND column_name = 'superseded_by'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.9 Verify packet_validation table
SELECT 
    'packet_validation table' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_validation'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 1.10 Verify packet_validation indexes
SELECT 
    indexname AS check_name,
    CASE 
        WHEN indexname IN (
            'idx_packet_validation_packet_active',
            'idx_packet_validation_doc_time',
            'idx_packet_validation_packet_time'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status
FROM pg_indexes
WHERE schemaname = 'service_ops'
  AND tablename = 'packet_validation'
ORDER BY indexname;

-- ============================================================================
-- SECTION 2: Verify Migration 018 - send_integration table
-- ============================================================================

-- 2.1 Verify send_integration table exists
SELECT 
    'send_integration table' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_integration'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 2.2 Verify all required columns exist
SELECT 
    column_name,
    data_type,
    is_nullable,
    CASE 
        WHEN column_name IN (
            'message_id', 'decision_tracking_id', 'workflow_instance_id',
            'payload', 'message_status_id', 'correlation_id', 'attempt_count',
            'resend_of_message_id', 'payload_hash', 'payload_version',
            'created_at', 'updated_at', 'audit_user', 'audit_timestamp', 'is_deleted'
        ) THEN 'PASS'
        ELSE 'UNEXPECTED'
    END AS status
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_integration'
ORDER BY ordinal_position;

-- 2.3 Verify send_integration indexes
SELECT 
    indexname AS check_name,
    CASE 
        WHEN indexname IN (
            'idx_send_integration_decision_tracking',
            'idx_send_integration_message_status',
            'idx_send_integration_correlation_id',
            'idx_send_integration_resend',
            'idx_send_integration_attempt_count',
            'idx_send_integration_decision_attempt',
            'idx_send_integration_created_at',
            'idx_send_integration_payload_gin',
            'idx_send_integration_message_type'
        ) THEN 'PASS'
        ELSE 'UNEXPECTED'
    END AS status
FROM pg_indexes
WHERE schemaname = 'service_ops'
  AND tablename = 'send_integration'
ORDER BY indexname;

-- 2.4 Verify foreign keys
SELECT 
    constraint_name AS check_name,
    CASE 
        WHEN constraint_name IN (
            'fk_send_integration_message_status',
            'fk_send_integration_workflow_instance',
            'fk_send_integration_resend'
        ) THEN 'PASS'
        ELSE 'UNEXPECTED'
    END AS status
FROM information_schema.table_constraints
WHERE constraint_schema = 'service_ops'
  AND table_name = 'send_integration'
  AND constraint_type = 'FOREIGN KEY'
ORDER BY constraint_name;

-- ============================================================================
-- SECTION 3: Verify Migration 019 - ClinicalOps watermark
-- ============================================================================

-- 3.1 Verify clinical_ops_poll_watermark table exists
SELECT 
    'clinical_ops_poll_watermark table' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'clinical_ops_poll_watermark'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- 3.2 Verify last_created_at column
SELECT 
    'clinical_ops_poll_watermark.last_created_at' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'clinical_ops_poll_watermark'
              AND column_name = 'last_created_at'
              AND data_type = 'timestamp with time zone'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    (SELECT data_type FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'clinical_ops_poll_watermark'
       AND column_name = 'last_created_at') AS data_type;

-- ============================================================================
-- SECTION 4: Verify Migration 020 - Timezone fixes
-- ============================================================================

-- 4.1 Verify send_serviceops.created_at is TIMESTAMPTZ
SELECT 
    'send_serviceops.created_at timezone' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_serviceops'
              AND column_name = 'created_at'
              AND data_type = 'timestamp with time zone'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    (SELECT data_type FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'send_serviceops'
       AND column_name = 'created_at') AS data_type;

-- 4.2 Verify integration_poll_watermark.last_created_at is TIMESTAMPTZ
SELECT 
    'integration_poll_watermark.last_created_at timezone' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'integration_poll_watermark'
              AND column_name = 'last_created_at'
              AND data_type = 'timestamp with time zone'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    (SELECT data_type FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'integration_poll_watermark'
       AND column_name = 'last_created_at') AS data_type;

-- ============================================================================
-- SECTION 5: Verify Migration 022 - json_sent_to_integration
-- ============================================================================

-- 5.1 Verify json_sent_to_integration column exists
SELECT 
    'send_serviceops.json_sent_to_integration' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_serviceops'
              AND column_name = 'json_sent_to_integration'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status,
    (SELECT data_type FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'send_serviceops'
       AND column_name = 'json_sent_to_integration') AS data_type,
    (SELECT column_default FROM information_schema.columns
     WHERE table_schema = 'service_ops'
       AND table_name = 'send_serviceops'
       AND column_name = 'json_sent_to_integration') AS default_value;

-- 5.2 Verify json_sent_to_integration index
SELECT 
    'idx_send_serviceops_json_sent index' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'service_ops'
              AND tablename = 'send_serviceops'
              AND indexname = 'idx_send_serviceops_json_sent'
        ) THEN 'PASS'
        ELSE 'FAIL'
    END AS status;

-- ============================================================================
-- SECTION 6: Data Integrity Checks
-- ============================================================================
-- Note: These checks use DO blocks with dynamic SQL to avoid parsing errors
-- when columns don't exist yet (safe for pre-migration state)

-- 6.1 Check for NULL values in required NOT NULL columns

-- 6.1.1 Check packet.validation_status NULL values
DO $$
DECLARE
    col_exists BOOLEAN;
    null_count INTEGER;
    status_text TEXT;
BEGIN
    -- Check if column exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND column_name = 'validation_status'
    ) INTO col_exists;
    
    IF col_exists THEN
        -- Use dynamic SQL to query the column (only parsed at runtime)
        EXECUTE 'SELECT COUNT(*) FROM service_ops.packet WHERE validation_status IS NULL' INTO null_count;
        
        status_text := CASE WHEN null_count > 0 THEN 'FAIL - NULL values found' ELSE 'PASS' END;
        
        RAISE NOTICE 'packet.validation_status NULL check: %, null_count: %', status_text, null_count;
    ELSE
        RAISE NOTICE 'packet.validation_status NULL check: SKIP - Column does not exist yet, null_count: NULL';
    END IF;
END $$;

-- 6.1.2 Check packet.detailed_status NULL values (this column should always exist)
SELECT 
    'packet.detailed_status NULL check' AS check_name,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM service_ops.packet
            WHERE detailed_status IS NULL
        ) THEN 'FAIL - NULL values found'
        ELSE 'PASS'
    END AS status,
    (SELECT COUNT(*) FROM service_ops.packet WHERE detailed_status IS NULL) AS null_count;

-- 6.1.3 Check packet_decision.operational_decision NULL values
DO $$
DECLARE
    col_exists BOOLEAN;
    null_count INTEGER;
    status_text TEXT;
BEGIN
    -- Check if column exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND column_name = 'operational_decision'
    ) INTO col_exists;
    
    IF col_exists THEN
        -- Use dynamic SQL to query the column (only parsed at runtime)
        EXECUTE 'SELECT COUNT(*) FROM service_ops.packet_decision WHERE operational_decision IS NULL' INTO null_count;
        
        status_text := CASE WHEN null_count > 0 THEN 'FAIL - NULL values found' ELSE 'PASS' END;
        
        RAISE NOTICE 'packet_decision.operational_decision NULL check: %, null_count: %', status_text, null_count;
    ELSE
        RAISE NOTICE 'packet_decision.operational_decision NULL check: SKIP - Column does not exist yet, null_count: NULL';
    END IF;
END $$;

-- 6.1.4 Check packet_decision.clinical_decision NULL values
DO $$
DECLARE
    col_exists BOOLEAN;
    null_count INTEGER;
    status_text TEXT;
BEGIN
    -- Check if column exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet_decision'
          AND column_name = 'clinical_decision'
    ) INTO col_exists;
    
    IF col_exists THEN
        -- Use dynamic SQL to query the column (only parsed at runtime)
        EXECUTE 'SELECT COUNT(*) FROM service_ops.packet_decision WHERE clinical_decision IS NULL' INTO null_count;
        
        status_text := CASE WHEN null_count > 0 THEN 'FAIL - NULL values found' ELSE 'PASS' END;
        
        RAISE NOTICE 'packet_decision.clinical_decision NULL check: %, null_count: %', status_text, null_count;
    ELSE
        RAISE NOTICE 'packet_decision.clinical_decision NULL check: SKIP - Column does not exist yet, null_count: NULL';
    END IF;
END $$;

-- 6.2 Check constraint violations

-- 6.2.1 Check packet.validation_status constraint violations
DO $$
DECLARE
    col_exists BOOLEAN;
    violation_count INTEGER;
    status_text TEXT;
BEGIN
    -- Check if column exists
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'service_ops'
          AND table_name = 'packet'
          AND column_name = 'validation_status'
    ) INTO col_exists;
    
    IF col_exists THEN
        -- Use dynamic SQL to query the column (only parsed at runtime)
        EXECUTE $$
            SELECT COUNT(*) FROM service_ops.packet
            WHERE validation_status NOT IN (
                'Pending - Validation',
                'Validation In Progress',
                'Pending - Manual Review',
                'Validation Updated',
                'Validation Complete',
                'Validation Failed'
            )
        $$ INTO violation_count;
        
        status_text := CASE WHEN violation_count > 0 THEN 'FAIL - Constraint violations found' ELSE 'PASS' END;
        
        RAISE NOTICE 'packet.validation_status constraint violations: %, violation_count: %', status_text, violation_count;
    ELSE
        RAISE NOTICE 'packet.validation_status constraint violations: SKIP - Column does not exist yet, violation_count: NULL';
    END IF;
END $$;

-- ============================================================================
-- SUMMARY
-- ============================================================================

SELECT 'Verification complete. Review all results above.' AS summary;

