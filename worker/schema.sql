-- Calendar Lab PostgreSQL Schema
-- All tables use UTC timestamps (TIMESTAMP WITHOUT TIME ZONE, stored as UTC)
-- IDs are typically BIGINT for extensibility, except lookup tables use INT

-- ============================================================
-- 1. LOOKUP TABLES (Reference data)
-- ============================================================

-- Day-off codes that can be deleted from calendar
CREATE TABLE IF NOT EXISTS lookup_day_off_codes (
    id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    code VARCHAR(10) NOT NULL UNIQUE,
    label_pt VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lookup_day_off_codes_code ON lookup_day_off_codes(code);

-- Airport/homebase reference for ASB->Reserva location resolution
CREATE TABLE IF NOT EXISTS lookup_homebases (
    id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    code VARCHAR(10) NOT NULL UNIQUE,
    airport_name VARCHAR(255) NOT NULL,
    city VARCHAR(100),
    state VARCHAR(50),
    country VARCHAR(100),
    address TEXT,
    coordinates JSONB,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lookup_homebases_code ON lookup_homebases(code);

-- Activity codes reference for Activity event translation
CREATE TABLE IF NOT EXISTS lookup_ground_activities (
    id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50),  -- "Presencial", "Online", etc.
    location VARCHAR(100),  -- airport code or "-" for online
    is_validated BOOLEAN DEFAULT TRUE,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_lookup_ground_activities_code ON lookup_ground_activities(code);

-- ============================================================
-- 2. RAW EVENTS (Immutable source data)
-- ============================================================

CREATE TABLE IF NOT EXISTS raw_events (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id VARCHAR(100) NOT NULL,
    source_uid VARCHAR(500) NOT NULL,
    start_utc TIMESTAMP NOT NULL,
    end_utc TIMESTAMP NOT NULL,
    summary VARCHAR(500),
    description TEXT,
    last_modified TIMESTAMP,
    raw_hash VARCHAR(64),  -- SHA256 hash for change detection
    processed_flag BOOLEAN DEFAULT FALSE,
    skip_reason VARCHAR(100),  -- reason if skipped: "start_time_removed", "day_off_code", etc.
    ingested_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, source_uid)
);
CREATE INDEX IF NOT EXISTS idx_raw_events_user_id_processed ON raw_events(user_id, processed_flag);
CREATE INDEX IF NOT EXISTS idx_raw_events_start_utc ON raw_events(user_id, start_utc);
CREATE INDEX IF NOT EXISTS idx_raw_events_source_uid ON raw_events(user_id, source_uid);

-- ============================================================
-- 3. PROCESSED EVENTS (Main normalized event table)
-- ============================================================

CREATE TABLE IF NOT EXISTS processed_events (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id VARCHAR(100) NOT NULL,
    source_uid VARCHAR(500) NOT NULL,
    raw_event_id BIGINT REFERENCES raw_events(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,  -- "Flight", "Activity", "Sobreaviso", "Reserva", "Apresentação", "DayOff", "Checkout", "Unknown"
    original_title TEXT,
    clean_title TEXT NOT NULL,
    activity_code VARCHAR(50),  -- for Activity events
    location_code VARCHAR(10),  -- for Reserva events (airport code)
    location_details JSONB,  -- full airport details from lookup_homebases
    start_utc TIMESTAMP NOT NULL,
    end_utc TIMESTAMP NOT NULL,
    notes TEXT,  -- with #roquescript-modified tag if modified
    notes_original TEXT,  -- preserved original notes
    event_url TEXT,
    is_synthetic BOOLEAN DEFAULT FALSE,  -- TRUE for Checkout events
    modifications JSONB,  -- array of modifications: [{rule: "...", at: "timestamp"}]
    tags JSONB,  -- array of tags: ["#roquescript-modified", "#activity-new", etc.]
    created_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    UNIQUE (user_id, source_uid)
);
CREATE INDEX IF NOT EXISTS idx_processed_events_user_id_type ON processed_events(user_id, event_type);
CREATE INDEX IF NOT EXISTS idx_processed_events_user_id_start ON processed_events(user_id, start_utc);
CREATE INDEX IF NOT EXISTS idx_processed_events_synthetic ON processed_events(user_id, is_synthetic);
CREATE INDEX IF NOT EXISTS idx_processed_events_activity_code ON processed_events(activity_code);

-- ============================================================
-- 4. AUDIT & HISTORY
-- ============================================================

CREATE TABLE IF NOT EXISTS processed_events_history (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    processed_event_id BIGINT REFERENCES processed_events(id) ON DELETE CASCADE,
    cycle_id UUID NOT NULL,
    operation VARCHAR(50),  -- "INSERT", "UPDATE", "DELETE", "SKIP"
    changes JSONB,
    performed_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_history_processed_event_cycle ON processed_events_history(processed_event_id, cycle_id);
CREATE INDEX IF NOT EXISTS idx_history_cycle_id ON processed_events_history(cycle_id);

-- Activity codes pending validation (auto-populated when unknown code found)
CREATE TABLE IF NOT EXISTS activity_codes_pending_validation (
    id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    code VARCHAR(50) NOT NULL UNIQUE,
    source_name TEXT,
    source_type VARCHAR(50),  -- "Presencial", "Online", etc.
    source_location VARCHAR(100),  -- airport code or "-"
    first_occurrence TIMESTAMP,
    last_occurrence TIMESTAMP,
    occurrence_count INT DEFAULT 1,
    admin_notes TEXT,
    status VARCHAR(20) DEFAULT 'pending',  -- "pending", "accepted", "rejected", "merged"
    merged_into_code VARCHAR(50),  -- if merged into existing code
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pending_validation_code ON activity_codes_pending_validation(code);
CREATE INDEX IF NOT EXISTS idx_pending_validation_status ON activity_codes_pending_validation(status);

-- Homebases pending validation (auto-populated when unknown location code found in ASB)
CREATE TABLE IF NOT EXISTS homebases_pending_validation (
    id INT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    code VARCHAR(10) NOT NULL UNIQUE,
    source_event_title TEXT,
    source_location_context TEXT,
    first_occurrence TIMESTAMP,
    last_occurrence TIMESTAMP,
    occurrence_count INT DEFAULT 1,
    admin_notes TEXT,
    status VARCHAR(20) DEFAULT 'pending',  -- "pending", "accepted", "rejected", "merged"
    merged_into_code VARCHAR(10),  -- if merged into existing homebase
    processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pending_homebases_code ON homebases_pending_validation(code);
CREATE INDEX IF NOT EXISTS idx_pending_homebases_status ON homebases_pending_validation(status);

-- ============================================================
-- 4.1 USER PARSING SETTINGS (future remote/custom options)
-- ============================================================

CREATE TABLE IF NOT EXISTS user_parsing_settings (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id VARCHAR(100) NOT NULL UNIQUE,
    dayoff_mode VARCHAR(20) NOT NULL DEFAULT 'remove', -- "remove", "timed", "all_day", "keep"
    dayoff_default_minutes INT,
    dayoff_per_code_minutes JSONB, -- {"DO": 1440, "DR": 720}
    settings_version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_user_parsing_settings_user_id ON user_parsing_settings(user_id);

-- ============================================================
-- 5. STATISTICS & AGGREGATES
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_duty_summary (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id VARCHAR(100) NOT NULL,
    duty_date DATE NOT NULL,  -- local date in SOURCE_TZ
    flight_count INT DEFAULT 0,
    flight_hours_decimal NUMERIC(5, 2),
    activity_count INT DEFAULT 0,
    sobreaviso_count INT DEFAULT 0,
    day_off_count INT DEFAULT 0,
    overnight_flight BOOLEAN DEFAULT FALSE,
    max_duty_time_minutes INT,
    computed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (user_id, duty_date)
);
CREATE INDEX IF NOT EXISTS idx_daily_duty_user_date ON daily_duty_summary(user_id, duty_date);

-- ============================================================
-- 6. CYCLE TRACKING (for idempotency management)
-- ============================================================

CREATE TABLE IF NOT EXISTS worker_cycles (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    cycle_id UUID NOT NULL UNIQUE,
    user_id VARCHAR(100),
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    status VARCHAR(20),  -- "running", "complete", "error", "partial_error"
    error_message TEXT,
    stats JSONB,  -- {events_ingested, events_processed, events_skipped, etc.}
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_worker_cycles_user_id ON worker_cycles(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_worker_cycles_status ON worker_cycles(status);
