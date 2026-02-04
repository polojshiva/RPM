-- Cleanup script to remove duplicate packet_decision records
-- Keep only the most recent active record for each packet_id

-- First, identify duplicates
SELECT 
    packet_id,
    COUNT(*) as record_count,
    MAX(packet_decision_id) as latest_id
FROM service_ops.packet_decision
WHERE packet_id = 3  -- Replace with your packet_id
GROUP BY packet_id
HAVING COUNT(*) > 1;

-- Keep only the most recent active record (is_active = true)
-- Deactivate all others
UPDATE service_ops.packet_decision
SET is_active = false
WHERE packet_id = 3  -- Replace with your packet_id
  AND packet_decision_id NOT IN (
      SELECT packet_decision_id
      FROM service_ops.packet_decision
      WHERE packet_id = 3
        AND is_active = true
      ORDER BY created_at DESC
      LIMIT 1
  );

-- Verify cleanup
SELECT 
    packet_decision_id,
    packet_id,
    clinical_decision,
    is_active,
    created_at
FROM service_ops.packet_decision
WHERE packet_id = 3
ORDER BY created_at DESC;

