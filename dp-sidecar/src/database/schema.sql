
-- TABLE 1: Release Windows (Time Periods)
CREATE TABLE IF NOT EXISTS release_windows (
    window_id SERIAL PRIMARY KEY,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_release_windows_status 
ON release_windows(status, end_time);


-- TABLE 2: DP Releases (Cached Noisy Counts per Window)
CREATE TABLE IF NOT EXISTS dp_releases (
    release_id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    window_id INTEGER REFERENCES release_windows(window_id),
    true_count INTEGER NOT NULL,
    noisy_count FLOAT NOT NULL,
    epsilon_used FLOAT NOT NULL,
    meets_threshold BOOLEAN DEFAULT FALSE,
    released_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(post_id, window_id)  -- One release per post per window
);

ALTER TABLE dp_releases 
ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'draft';

-- Add index for fast status lookups
CREATE INDEX IF NOT EXISTS idx_dp_releases_status 
ON dp_releases(post_id, window_id, status);

-- Update existing rows to be 'published' (migration)
UPDATE dp_releases SET status = 'published' WHERE status IS NULL;

CREATE INDEX IF NOT EXISTS idx_dp_releases_post_window 
ON dp_releases(post_id, window_id);


-- TABLE 3: Epsilon Budget (Detailed Budget per Window)
CREATE TABLE IF NOT EXISTS epsilon_budget (
    budget_id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    window_id INTEGER REFERENCES release_windows(window_id),
    epsilon_remaining FLOAT NOT NULL,
    monthly_epsilon_cap FLOAT NOT NULL DEFAULT 20.0,
    is_locked BOOLEAN DEFAULT FALSE,
    locked_at TIMESTAMP,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(post_id, window_id)  -- One budget per post per window
);

CREATE INDEX IF NOT EXISTS idx_epsilon_budget_post_window 
ON epsilon_budget(post_id, window_id);

CREATE INDEX IF NOT EXISTS idx_epsilon_budget_locked 
ON epsilon_budget(is_locked) WHERE is_locked = TRUE;


-- TABLE 4: DP Items (Quick Lookup Summary per Post)
CREATE TABLE IF NOT EXISTS dp_items (
    post_id INTEGER PRIMARY KEY,
    current_window_id INTEGER,
    last_true_count INTEGER NOT NULL DEFAULT 0,
    is_currently_locked BOOLEAN NOT NULL DEFAULT FALSE,
    total_epsilon_spent FLOAT NOT NULL DEFAULT 0,  -- Lifetime total
    last_updated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dp_items_locked 
ON dp_items(is_currently_locked) WHERE is_currently_locked = TRUE;


-- HELPER FUNCTION: Update dp_items when epsilon_budget changes
-- This keeps dp_items in sync with epsilon_budget automatically
CREATE OR REPLACE FUNCTION update_dp_items_summary()
RETURNS TRIGGER AS $$
BEGIN
    -- Update or insert into dp_items
    INSERT INTO dp_items (post_id, current_window_id, is_currently_locked, last_updated)
    VALUES (NEW.post_id, NEW.window_id, NEW.is_locked, NOW())
    ON CONFLICT (post_id) 
    DO UPDATE SET
        current_window_id = NEW.window_id,
        is_currently_locked = NEW.is_locked,
        last_updated = NOW();
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-update dp_items when epsilon_budget changes
CREATE TRIGGER trigger_update_dp_items
AFTER INSERT OR UPDATE ON epsilon_budget
FOR EACH ROW
EXECUTE FUNCTION update_dp_items_summary();


-- HELPER FUNCTION: Update total epsilon spent
CREATE OR REPLACE FUNCTION update_total_epsilon_spent()
RETURNS TRIGGER AS $$
BEGIN
    -- Add epsilon to lifetime total
    UPDATE dp_items
    SET total_epsilon_spent = total_epsilon_spent + (NEW.epsilon_used - COALESCE(OLD.epsilon_used, 0))
    WHERE post_id = NEW.post_id;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Auto-update total epsilon when dp_releases changes
CREATE TRIGGER trigger_update_total_epsilon
AFTER INSERT OR UPDATE ON dp_releases
FOR EACH ROW
EXECUTE FUNCTION update_total_epsilon_spent();