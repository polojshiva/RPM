-- Migration: Add channel_type_id to integration_inbox
-- Purpose: Track channel type (1=Portal, 2=Fax, 3=ESMD) through processing lifecycle
-- Schema: service_ops
-- Date: 2026-01-07

BEGIN;

-- ============================================================================
-- 1. Add channel_type_id column to integration_inbox
-- ============================================================================
ALTER TABLE service_ops.integration_inbox
ADD COLUMN IF NOT EXISTS channel_type_id BIGINT;

-- ============================================================================
-- 2. Add index for channel_type_id lookups
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_integration_inbox_channel_type_id 
    ON service_ops.integration_inbox(channel_type_id)
    WHERE channel_type_id IS NOT NULL;

-- ============================================================================
-- 3. Add comment
-- ============================================================================
COMMENT ON COLUMN service_ops.integration_inbox.channel_type_id IS 
    'Channel type ID: 1=Genzeon Portal, 2=Genzeon Fax, 3=ESMD. NULL for backward compatibility with old messages.';

COMMIT;






