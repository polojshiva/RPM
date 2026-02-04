-- Manually update submission_type for a specific packet
-- This will immediately show in the UI dashboard

-- For PKT-2026-503899:
UPDATE service_ops.packet
SET 
    submission_type = 'Expedited',
    updated_at = NOW()
WHERE external_id = 'PKT-2026-503899';

-- Verify the update
SELECT 
    external_id,
    submission_type,
    updated_at
FROM service_ops.packet
WHERE external_id = 'PKT-2026-503899';

-- To update multiple packets at once:
-- UPDATE service_ops.packet
-- SET submission_type = 'Expedited'
-- WHERE external_id IN ('PKT-2026-503899', 'PKT-2026-XXXXXX');

-- To set to Standard:
-- UPDATE service_ops.packet
-- SET submission_type = 'Standard'
-- WHERE external_id = 'PKT-2026-503899';

