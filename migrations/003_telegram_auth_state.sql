-- migrations/003_telegram_auth_state.sql
-- Add Telegram authentication state tracking

CREATE TABLE IF NOT EXISTS telegram_auth_state (
    phone_number TEXT PRIMARY KEY,
    phone_code_hash TEXT NOT NULL,
    next_step TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create index for quick cleanup of old states
CREATE INDEX IF NOT EXISTS idx_telegram_auth_state_updated 
ON telegram_auth_state(updated_at);