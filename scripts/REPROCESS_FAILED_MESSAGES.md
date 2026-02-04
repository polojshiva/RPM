# How to Reprocess Failed Messages After 100% Reliability Fix

## Overview

After pushing the 100% reliability code, the 12-13 failed messages will be processed **IF** they are picked up by the poller. However, the poller uses a watermark to only process NEW messages (after `last_created_at`).

## The 13 Failed Messages

Based on the earlier analysis:
- **4 records**: Text files (.txt) - Will now auto-convert to PDF ✅
- **6 records**: Missing documents field - Will now create packets with empty state ✅
- **2 records**: Empty documents array - Will now create packets with empty state ✅
- **1 record**: Watermark timing - Will be picked up in next poll ✅

## Prerequisites

1. **Verify message_type_id**: All failed messages must have `message_type_id = 1` (or NULL)
   - If they have `message_type_id = 2`, they will be skipped (different workflow)

2. **Check if messages still exist**: Verify the messages are still in `integration.send_serviceops` table

## Option 1: Reset Watermark (Recommended)

Reset the watermark to before the failed messages so they get picked up:

```bash
# Reset to before a specific date
python scripts/reset_watermark_for_reprocessing.py --before-date "2026-01-10 00:00:00"

# Or reset for specific message IDs
python scripts/reset_watermark_for_reprocessing.py --message-ids 594,593,592,591,601,598,597,121,120,119,361,306,602

# Or reset to beginning (reprocesses ALL messages - use with caution!)
python scripts/reset_watermark_for_reprocessing.py --reset-to-beginning
```

**After resetting**, the poller will pick them up in the next poll cycle (every 5 minutes).

## Option 2: Manual SQL Reset

If you prefer SQL:

```sql
-- Check current watermark
SELECT last_created_at, last_message_id 
FROM service_ops.integration_poll_watermark 
WHERE id = 1;

-- Reset to before failed messages (adjust date as needed)
UPDATE service_ops.integration_poll_watermark
SET last_created_at = '2026-01-10 00:00:00+00'::timestamptz,
    last_message_id = 0
WHERE id = 1;
```

## Option 3: Verify Messages Will Be Processed

Check if messages meet the new filter criteria:

```sql
-- Check which messages will be processed with new code
SELECT 
    message_id,
    decision_tracking_id,
    created_at,
    message_type_id,
    CASE 
        WHEN message_type_id = 1 OR message_type_id IS NULL THEN '✅ Will be processed'
        WHEN message_type_id = 2 THEN '❌ Will be skipped (type 2)'
        ELSE '❓ Unknown type'
    END as status,
    CASE 
        WHEN payload->>'documents' IS NULL THEN 'Missing documents'
        WHEN jsonb_array_length(payload->'documents') = 0 THEN 'Empty documents'
        ELSE 'Has documents'
    END as document_status
FROM integration.send_serviceops
WHERE message_id IN (594, 593, 592, 591, 601, 598, 597, 121, 120, 119, 361, 306, 602)
  AND is_deleted = false
ORDER BY message_id;
```

## Expected Results After Reprocessing

| Message ID | Issue | Expected Result |
|------------|-------|----------------|
| 594, 593, 592, 591 | Text files (.txt) | ✅ Auto-converted to PDF, packet created |
| 601, 598, 597, 121, 120, 119 | Missing documents | ✅ Packet created with empty document state |
| 361, 306 | Empty documents array | ✅ Packet created with empty document state |
| 602 | Watermark timing | ✅ Picked up in next poll |

## Verification

After reprocessing, verify packets were created:

```sql
-- Check if packets were created for the failed messages
SELECT 
    p.packet_id,
    p.external_id,
    p.decision_tracking_id,
    p.received_date,
    pd.packet_document_id,
    pd.file_name,
    pd.split_status,
    pd.ocr_status,
    CASE 
        WHEN pd.file_name = 'no_documents.pdf' THEN 'Empty document state'
        ELSE 'Normal document'
    END as document_type
FROM service_ops.packet p
LEFT JOIN service_ops.packet_document pd ON p.packet_id = pd.packet_id
WHERE p.decision_tracking_id IN (
    SELECT decision_tracking_id 
    FROM integration.send_serviceops 
    WHERE message_id IN (594, 593, 592, 591, 601, 598, 597, 121, 120, 119, 361, 306, 602)
)
ORDER BY p.created_at DESC;
```

## Important Notes

1. **Idempotency**: If packets already exist for these `decision_tracking_id`s, they will be reused (not duplicated)

2. **Empty Document State**: Messages with missing/empty documents will create packets with:
   - `file_name = 'no_documents.pdf'`
   - `split_status = 'SKIPPED'`
   - `ocr_status = 'SKIPPED'`
   - `extracted_fields.source = 'MISSING_DOCUMENTS'`

3. **Text File Conversion**: Text files will be automatically converted to PDF during merge

4. **Watermark**: After reprocessing, the watermark will advance past these messages

## Troubleshooting

If messages still don't get processed:

1. **Check message_type_id**: Must be 1 or NULL
   ```sql
   SELECT message_id, message_type_id 
   FROM integration.send_serviceops 
   WHERE message_id IN (...);
   ```

2. **Check is_deleted flag**: Must be false
   ```sql
   SELECT message_id, is_deleted 
   FROM integration.send_serviceops 
   WHERE message_id IN (...);
   ```

3. **Check decision_tracking_id**: Must exist
   ```sql
   SELECT message_id, decision_tracking_id 
   FROM integration.send_serviceops 
   WHERE message_id IN (...);
   ```

4. **Check inbox status**: See if they're stuck in inbox
   ```sql
   SELECT inbox_id, decision_tracking_id, status, attempt_count
   FROM service_ops.integration_inbox
   WHERE decision_tracking_id IN (
       SELECT decision_tracking_id 
       FROM integration.send_serviceops 
       WHERE message_id IN (...)
   );
   ```

