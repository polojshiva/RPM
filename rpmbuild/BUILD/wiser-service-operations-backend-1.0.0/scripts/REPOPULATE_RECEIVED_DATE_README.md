# Repopulate Received Date from Original Payloads

## Overview

This script repopulates `packet.received_date` with raw timestamps extracted from original payloads stored in `integration.send_serviceops`. This fixes existing packets that were normalized to midnight (00:00:00) and restores their original timestamps.

## Why This Is Needed

Previously, the code normalized submission dates to midnight before storing them in `packet.received_date`. The new code stores raw timestamps, but existing records still have midnight times. This script extracts the original timestamps from the payloads and updates the database.

## Important Note About New Code

**The new code will NOT normalize existing records.** The normalization logic only runs when processing NEW messages from `integration.send_serviceops`. When reading existing packets from the database, the code uses whatever value is stored in `packet.received_date` (whether it's normalized or not).

## Usage

### Option 1: Python Script (Recommended)

The Python script provides better error handling and detailed logging:

```bash
# Preview changes (dry run)
python scripts/repopulate_received_date_from_payload.py --dry-run

# Preview first 5 packets
python scripts/repopulate_received_date_from_payload.py --dry-run --limit 5

# Apply changes to all packets
python scripts/repopulate_received_date_from_payload.py

# Apply changes to first 100 packets (for testing)
python scripts/repopulate_received_date_from_payload.py --limit 100
```

**Requirements:**
- `DATABASE_URL` or `POSTGRES_URL` environment variable must be set
- Python dependencies: `sqlalchemy`, `python-dateutil`

### Option 2: SQL Script

For direct database access, use the SQL script:

```sql
-- 1. Preview what will be updated
-- Run the SELECT query in repopulate_received_date_from_payload.sql

-- 2. Review the results

-- 3. Run the UPDATE query in a transaction
BEGIN;
-- ... run UPDATE query ...
-- Review changes
-- COMMIT; or ROLLBACK;
```

## What the Script Does

1. **Finds packets with normalized dates**: Identifies packets where `received_date` is at midnight (00:00:00)

2. **Extracts original timestamp from payload**:
   - **ESMD (channel_type_id=3)**: `payload.submission_metadata.creationTime`
   - **Portal (channel_type_id=1)**: `payload.ocr.fields["Submitted Date"].value`
   - **Fax (channel_type_id=2)**: `payload.submission_metadata.creationTime` or `payload.extracted_fields.fields["Submitted Date"].value`

3. **Falls back to message.created_at**: If submission date can't be extracted from payload, uses `integration.send_serviceops.created_at`

4. **Updates packet.received_date**: Sets the raw timestamp (preserving original time)

5. **Skips if no change needed**: Doesn't update if:
   - New date is same as current date
   - New date is also at midnight (no time information available)

## Example Output

```
================================================================================
REPOPULATING RECEIVED_DATE FROM ORIGINAL PAYLOADS
================================================================================
Mode: DRY RUN (preview only)
================================================================================

Found 2000 packets with normalized received_date (midnight times)
--------------------------------------------------------------------------------

[1/2000] Processing packet: SVC-2026-1234567 (ID: 123)
  Current received_date: 2026-01-06 00:00:00+00:00
  Channel type: 3 (ESMD)
  Extracted from payload: 2026-01-06 14:25:33.439221+00:00
  New received_date: 2026-01-06 14:25:33.439221+00:00 (source: payload)
  Time difference: 14:25:33
  [DRY RUN] Would update packet.received_date

[2/2000] Processing packet: SVC-2026-1234568 (ID: 124)
  Current received_date: 2026-01-07 00:00:00+00:00
  Channel type: 1 (Portal)
  Extracted from payload: 2026-01-07 09:30:00+00:00
  New received_date: 2026-01-07 09:30:00+00:00 (source: payload)
  Time difference: 9:30:0
  [DRY RUN] Would update packet.received_date

================================================================================
SUMMARY
================================================================================
Total packets processed: 2000
Updated: 1850
Skipped: 150
Errors: 0
================================================================================
```

## Safety Features

1. **Dry run mode**: Preview changes before applying
2. **Transaction support**: SQL script uses transactions
3. **Selective updates**: Only updates packets with midnight times
4. **Validation**: Skips updates if new date is also at midnight
5. **Error handling**: Python script catches and reports errors

## After Running

Once the script completes:

1. **New packets** will automatically store raw timestamps (new code handles this)
2. **Existing packets** will have their original timestamps restored
3. **SLA calculations** will normalize dates internally (no change to stored values)

## Verification

Check that packets now have non-midnight times:

```sql
SELECT 
    packet_id,
    external_id,
    received_date,
    EXTRACT(HOUR FROM received_date) as hour,
    EXTRACT(MINUTE FROM received_date) as minute,
    EXTRACT(SECOND FROM received_date) as second
FROM service_ops.packet
WHERE EXTRACT(HOUR FROM received_date) != 0 
   OR EXTRACT(MINUTE FROM received_date) != 0 
   OR EXTRACT(SECOND FROM received_date) != 0
ORDER BY packet_id DESC
LIMIT 10;
```

## Troubleshooting

### No packets found to update
- All packets may already have raw timestamps
- Or all packets have midnight times in payloads (no time information available)

### Some packets skipped
- Payload doesn't contain submission date
- Submission date in payload is also at midnight
- Payload structure doesn't match expected format

### Errors during update
- Check database permissions
- Verify `integration.send_serviceops` table exists and is accessible
- Check that `decision_tracking_id` matches between tables
