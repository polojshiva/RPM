-- Create clinical_ops_poll_watermark table if it doesn't exist
CREATE TABLE IF NOT EXISTS service_ops.clinical_ops_poll_watermark (
    id INTEGER PRIMARY KEY DEFAULT 1,
    last_message_id BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT single_row CHECK (id = 1)
);

-- Insert initial row if it doesn't exist
INSERT INTO service_ops.clinical_ops_poll_watermark (id, last_message_id)
VALUES (1, 0)
ON CONFLICT (id) DO NOTHING;

