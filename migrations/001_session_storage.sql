-- SQL Migration for Instagram Session Storage

-- Create sessions table
CREATE TABLE IF NOT EXISTS instagram_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    session_type TEXT NOT NULL,  -- 'firefox' or 'cookies_file'
    cookies_file_path TEXT,      -- Path to cookies.txt file if session_type is 'cookies_file'
    session_data TEXT NOT NULL,  -- JSON encoded cookie data
    is_active BOOLEAN DEFAULT 0,
    last_validated TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,        -- When the session is expected to expire
    UNIQUE(user_id, session_type, cookies_file_path)
);

-- Create session validation history table
CREATE TABLE IF NOT EXISTS session_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    validation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_valid BOOLEAN NOT NULL,
    error_message TEXT,
    FOREIGN KEY(session_id) REFERENCES instagram_sessions(id) ON DELETE CASCADE
);

-- Add indexes
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON instagram_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON instagram_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_validations_session ON session_validations(session_id);