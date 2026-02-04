-- Migration 025: Create background_task_leader table for leader election
-- Purpose: Enable database-based leader election for background tasks (message_poller, clinical_ops_processor)
-- Schema: service_ops
-- Date: 2026-01-23

BEGIN;

-- Create the leader election table
CREATE TABLE IF NOT EXISTS service_ops.background_task_leader (
    task_name VARCHAR(100) PRIMARY KEY,
    worker_id VARCHAR(200) NOT NULL,
    heartbeat_at TIMESTAMP NOT NULL,
    elected_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Add comments for documentation
COMMENT ON TABLE service_ops.background_task_leader IS 
    'Leader election table for background tasks. Ensures only one instance of each task runs across all Gunicorn workers.';

COMMENT ON COLUMN service_ops.background_task_leader.task_name IS 
    'Unique name for the background task (e.g., message_poller, clinical_ops_processor)';

COMMENT ON COLUMN service_ops.background_task_leader.worker_id IS 
    'Unique identifier for the worker instance that is the current leader';

COMMENT ON COLUMN service_ops.background_task_leader.heartbeat_at IS 
    'Last heartbeat timestamp. If heartbeat is older than 90 seconds, leader is considered stale.';

COMMENT ON COLUMN service_ops.background_task_leader.elected_at IS 
    'Timestamp when this worker became the leader';

COMMENT ON COLUMN service_ops.background_task_leader.updated_at IS 
    'Last update timestamp (auto-updated on any change)';

-- Create index on heartbeat_at for faster stale leader detection
CREATE INDEX IF NOT EXISTS idx_background_task_leader_heartbeat 
ON service_ops.background_task_leader(heartbeat_at);

COMMENT ON INDEX service_ops.idx_background_task_leader_heartbeat IS 
    'Index for efficient stale leader detection queries';

COMMIT;
