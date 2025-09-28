-- migrations/002_telegram_sessions.sql
-- Add Telegram session storage support

CREATE TABLE IF NOT EXISTS telegram_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_name TEXT NOT NULL,
    session_file_path TEXT NOT NULL,
    session_data TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_telegram_sessions_active 
ON telegram_sessions(is_active, expires_at);

CREATE INDEX IF NOT EXISTS idx_telegram_sessions_name 
ON telegram_sessions(session_name);

-- Create unique constraint to prevent duplicate active sessions
CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_sessions_unique_active 
ON telegram_sessions(session_name) WHERE is_active = TRUE;