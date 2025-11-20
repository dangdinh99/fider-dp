-- Release windows (daily or weekly periods)
CREATE TABLE IF NOT EXISTS release_windows (
    window_id SERIAL PRIMARY KEY,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

-- DP releases per item per window
CREATE TABLE IF NOT EXISTS dp_releases (
    release_id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    window_id INTEGER REFERENCES release_windows(window_id),
    true_count INTEGER NOT NULL,
    noisy_count FLOAT NOT NULL,
    epsilon_used FLOAT NOT NULL,
    meets_threshold BOOLEAN DEFAULT FALSE,
    released_at TIMESTAMP DEFAULT NOW()
);

-- Epsilon budget tracking per post per window
CREATE TABLE IF NOT EXISTS epsilon_budget (
    budget_id SERIAL PRIMARY KEY,
    post_id INTEGER NOT NULL,
    window_id INTEGER REFERENCES release_windows(window_id),
    epsilon_remaining FLOAT NOT NULL,
    monthly_epsilon_cap FLOAT NOT NULL,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(post_id, window_id)
);

-- Indexes for faster queries
CREATE INDEX IF NOT EXISTS idx_dp_releases_post_window 
ON dp_releases(post_id, window_id);

CREATE INDEX IF NOT EXISTS idx_budget_post_window 
ON epsilon_budget(post_id, window_id);