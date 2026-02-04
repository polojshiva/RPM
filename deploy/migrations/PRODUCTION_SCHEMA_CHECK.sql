-- Production Schema Compatibility Check
-- Run these queries against production to verify current state before migrations
-- DO NOT MODIFY ANYTHING - READ ONLY QUERIES

-- ============================================================================
-- 1. Check if service_ops.send_serviceops table exists and its structure
-- ============================================================================
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default,
    character_maximum_length
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_serviceops'
ORDER BY ordinal_position;

-- Check if json_sent_to_integration column already exists
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_serviceops'
              AND column_name = 'json_sent_to_integration'
        ) THEN 'EXISTS'
        ELSE 'NOT EXISTS'
    END AS json_sent_to_integration_status;

-- Count existing records in send_serviceops
SELECT 
    COUNT(*) as total_records,
    COUNT(CASE WHEN created_at IS NOT NULL THEN 1 END) as records_with_created_at,
    MIN(created_at) as oldest_record,
    MAX(created_at) as newest_record
FROM service_ops.send_serviceops
WHERE is_deleted = false;

-- ============================================================================
-- 2. Check if service_ops.send_integration table exists
-- ============================================================================
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'send_integration'
        ) THEN 'EXISTS'
        ELSE 'NOT EXISTS'
    END AS send_integration_table_status;

-- If table exists, check its structure
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_integration'
ORDER BY ordinal_position;

-- ============================================================================
-- 3. Check service_ops.packet table structure (for Migration 017)
-- ============================================================================
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

-- Check existing values in validation_status (if column exists)
SELECT 
    validation_status,
    COUNT(*) as count
FROM service_ops.packet
WHERE validation_status IS NOT NULL
GROUP BY validation_status
ORDER BY count DESC;

-- Check NULL values in detailed_status
SELECT 
    COUNT(*) as total_records,
    COUNT(detailed_status) as records_with_detailed_status,
    COUNT(CASE WHEN detailed_status IS NULL THEN 1 END) as null_detailed_status
FROM service_ops.packet;

-- ============================================================================
-- 4. Check service_ops.packet_decision table structure (for Migration 017)
-- ============================================================================
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

-- Check existing values in operational_decision (if column exists)
SELECT 
    operational_decision,
    COUNT(*) as count
FROM service_ops.packet_decision
WHERE operational_decision IS NOT NULL
GROUP BY operational_decision
ORDER BY count DESC;

-- Check existing values in clinical_decision (if column exists)
SELECT 
    clinical_decision,
    COUNT(*) as count
FROM service_ops.packet_decision
WHERE clinical_decision IS NOT NULL
GROUP BY clinical_decision
ORDER BY count DESC;

-- ============================================================================
-- 5. Check if packet_validation table exists (Migration 017)
-- ============================================================================
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'packet_validation'
        ) THEN 'EXISTS'
        ELSE 'NOT EXISTS'
    END AS packet_validation_table_status;

-- ============================================================================
-- 6. Check timezone columns (for Migration 020)
-- ============================================================================
-- Check created_at column type in send_serviceops
SELECT 
    column_name,
    data_type,
    datetime_precision
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'send_serviceops'
  AND column_name = 'created_at';

-- Check if clinical_ops_poll_watermark exists and its structure
SELECT 
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'service_ops'
  AND table_name = 'clinical_ops_poll_watermark'
ORDER BY ordinal_position;

-- ============================================================================
-- 7. Check for existing data that might be affected
-- ============================================================================
-- Count records in send_serviceops by date range (to understand data volume)
SELECT 
    DATE_TRUNC('day', created_at) as date,
    COUNT(*) as record_count
FROM service_ops.send_serviceops
WHERE is_deleted = false
  AND created_at IS NOT NULL
GROUP BY DATE_TRUNC('day', created_at)
ORDER BY date DESC
LIMIT 30;

-- Check if there are any records that might conflict with new constraints
-- (This checks for records that don't match the new validation_status constraint)
SELECT 
    COUNT(*) as records_with_invalid_validation_status
FROM service_ops.packet
WHERE validation_status IS NOT NULL
  AND validation_status NOT IN (
    'Pending - Validation',
    'Validation In Progress',
    'Pending - Manual Review',
    'Validation Updated',
    'Validation Complete',
    'Validation Failed'
  );

-- Check for records with invalid detailed_status
SELECT 
    COUNT(*) as records_with_invalid_detailed_status
FROM service_ops.packet
WHERE detailed_status IS NOT NULL
  AND detailed_status NOT IN (
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
  );

-- ============================================================================
-- 8. Check foreign key constraints and dependencies
-- ============================================================================
-- Check if message_status table exists (required for send_integration FK)
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'message_status'
        ) THEN 'EXISTS'
        ELSE 'NOT EXISTS'
    END AS message_status_table_status;

-- Check if workflow_instance table exists (required for send_integration FK)
SELECT 
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'service_ops'
              AND table_name = 'workflow_instance'
        ) THEN 'EXISTS'
        ELSE 'NOT EXISTS'
    END AS workflow_instance_table_status;

-- ============================================================================
-- 9. Summary Query - Get all tables in service_ops schema
-- ============================================================================
SELECT 
    table_name,
    (SELECT COUNT(*) FROM information_schema.columns 
     WHERE table_schema = 'service_ops' 
       AND table_name = t.table_name) as column_count
FROM information_schema.tables t
WHERE table_schema = 'service_ops'
ORDER BY table_name;

