-- Verification Script for End-to-End Testing
-- Run this after testing "Send to Clinical Ops" and "Dismissal" flows
-- Shows all records created in each table

-- ============================================================================
-- 1. Packet Records
-- ============================================================================
SELECT 
    '=== PACKET RECORDS ===' AS section;

SELECT 
    packet_id,
    external_id,
    decision_tracking_id,
    case_id,
    beneficiary_name,
    beneficiary_mbi,
    provider_name,
    provider_npi,
    detailed_status,
    validation_status,
    assigned_to,
    received_date,
    due_date,
    channel_type_id,
    created_at
FROM service_ops.packet
ORDER BY created_at DESC;

-- ============================================================================
-- 2. Document Records
-- ============================================================================
SELECT 
    '=== DOCUMENT RECORDS ===' AS section;

SELECT 
    packet_document_id,
    external_id,
    packet_id,
    file_name,
    document_type_id,
    page_count,
    coversheet_page_number,
    part_type,
    ocr_status,
    split_status,
    created_at
FROM service_ops.packet_document
ORDER BY created_at DESC;

-- ============================================================================
-- 3. Validation Records (with is_active flag)
-- ============================================================================
SELECT 
    '=== VALIDATION RECORDS (ACTIVE) ===' AS section;

SELECT 
    packet_validation_id,
    packet_id,
    packet_document_id,
    validation_type,
    validation_status,
    is_passed,
    is_active,
    validated_by,
    validated_at,
    created_at
FROM service_ops.packet_validation
WHERE is_active = true
ORDER BY validated_at DESC;

SELECT 
    '=== VALIDATION RECORDS (ALL - FOR AUDIT TRAIL) ===' AS section;

SELECT 
    packet_validation_id,
    packet_id,
    validation_type,
    validation_status,
    is_passed,
    is_active,
    validated_by,
    validated_at,
    supersedes,
    superseded_by
FROM service_ops.packet_validation
ORDER BY packet_id, validated_at DESC;

-- ============================================================================
-- 4. Decision Records (with is_active flag)
-- ============================================================================
SELECT 
    '=== DECISION RECORDS (ACTIVE) ===' AS section;

SELECT 
    packet_decision_id,
    packet_id,
    packet_document_id,
    decision_type,
    operational_decision,
    clinical_decision,
    is_active,
    created_by,
    created_at,
    notes
FROM service_ops.packet_decision
WHERE is_active = true
ORDER BY created_at DESC;

SELECT 
    '=== DECISION RECORDS (ALL - FOR AUDIT TRAIL) ===' AS section;

SELECT 
    packet_decision_id,
    packet_id,
    decision_type,
    operational_decision,
    clinical_decision,
    is_active,
    supersedes,
    superseded_by,
    created_by,
    created_at
FROM service_ops.packet_decision
ORDER BY packet_id, created_at DESC;

-- ============================================================================
-- 5. ClinicalOps Outbox Records (send_clinicalops)
-- ============================================================================
SELECT 
    '=== CLINICALOPS OUTBOX (send_clinicalops) ===' AS section;

SELECT 
    message_id,
    decision_tracking_id,
    payload->>'message_type' AS message_type,
    payload->>'packet_id' AS packet_id,
    payload->'validation_summary' AS validation_summary,
    payload->'packet_data'->>'beneficiary_name' AS beneficiary_name,
    payload->'packet_data'->>'provider_name' AS provider_name,
    audit_user,
    created_at
FROM service_ops.send_clinicalops
WHERE is_deleted = false
ORDER BY created_at DESC;

-- ============================================================================
-- 6. Integration Outbox Records (service_ops.send_integration)
-- ============================================================================
SELECT 
    '=== INTEGRATION OUTBOX (service_ops.send_integration) ===' AS section;

SELECT 
    response_id,
    decision_tracking_id,
    decision_type,
    status,
    attempt_count,
    created_at
FROM service_ops.send_integration
ORDER BY created_at DESC;

-- ============================================================================
-- 7. Summary Counts
-- ============================================================================
SELECT 
    '=== SUMMARY COUNTS ===' AS section;

SELECT 
    'Packets' AS table_name,
    COUNT(*) AS total_count,
    COUNT(CASE WHEN detailed_status = 'Pending - Clinical Review' THEN 1 END) AS pending_clinical_review,
    COUNT(CASE WHEN detailed_status LIKE '%Dismissal%' THEN 1 END) AS dismissal_count
FROM service_ops.packet
UNION ALL
SELECT 
    'Documents',
    COUNT(*),
    NULL,
    NULL
FROM service_ops.packet_document
UNION ALL
SELECT 
    'Active Validations',
    COUNT(*),
    COUNT(CASE WHEN is_passed = true THEN 1 END) AS passed_count,
    COUNT(CASE WHEN is_passed = false THEN 1 END) AS failed_count
FROM service_ops.packet_validation
WHERE is_active = true
UNION ALL
SELECT 
    'Active Decisions',
    COUNT(*),
    COUNT(CASE WHEN operational_decision = 'PENDING' THEN 1 END) AS pending_ops,
    COUNT(CASE WHEN operational_decision = 'DISMISSAL' THEN 1 END) AS dismissal_ops
FROM service_ops.packet_decision
WHERE is_active = true
UNION ALL
SELECT 
    'ClinicalOps Outbox',
    COUNT(*),
    COUNT(CASE WHEN payload->>'message_type' = 'CASE_READY_FOR_REVIEW' THEN 1 END) AS case_ready_count,
    NULL
FROM service_ops.send_clinicalops
WHERE is_deleted = false;

-- ============================================================================
-- 8. Workflow Status Summary
-- ============================================================================
SELECT 
    '=== WORKFLOW STATUS SUMMARY ===' AS section;

SELECT 
    p.external_id AS packet_id,
    p.detailed_status,
    p.validation_status,
    p.assigned_to,
    CASE 
        WHEN pd.operational_decision IS NOT NULL THEN pd.operational_decision
        ELSE 'N/A'
    END AS operational_decision,
    CASE 
        WHEN pd.clinical_decision IS NOT NULL THEN pd.clinical_decision
        ELSE 'N/A'
    END AS clinical_decision,
    CASE 
        WHEN EXISTS (
            SELECT 1 FROM service_ops.send_clinicalops sc
            WHERE sc.decision_tracking_id = p.decision_tracking_id::text
            AND sc.is_deleted = false
        ) THEN 'YES'
        ELSE 'NO'
    END AS sent_to_clinicalops,
    p.created_at
FROM service_ops.packet p
LEFT JOIN service_ops.packet_decision pd ON pd.packet_id = p.packet_id AND pd.is_active = true
ORDER BY p.created_at DESC;

