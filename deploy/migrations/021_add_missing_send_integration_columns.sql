-- Migration 021: Add missing columns to service_ops.send_integration if they don't exist
-- Purpose: Ensure all columns from migration 018 are present
-- Schema: service_ops
-- Date: 2026-01-14

BEGIN;

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
        
        COMMENT ON COLUMN service_ops.send_integration.correlation_id IS 
            'UUID for tracking resends and correlating multiple requests per decision_tracking_id';
    END IF;
END $$;

-- Add workflow_instance_id if it doesn't exist
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

-- Create correlation_id index if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_send_integration_correlation_id 
    ON service_ops.send_integration(correlation_id) 
    WHERE correlation_id IS NOT NULL;

COMMIT;

