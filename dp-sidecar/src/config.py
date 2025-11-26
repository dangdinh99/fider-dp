"""
Configuration for DP parameters and database connections.
"""

# ===== DP PARAMETERS =====
THRESHOLD = 1                  # Minimum votes before releasing count
EPSILON_PER_QUERY = 0.5         # Privacy budget per release
SENSITIVITY = 1                 # One vote per user
MONTHLY_EPSILON_CAP = 20.0      # Maximum epsilon per post 

# ===== RELEASE SCHEDULE =====
WINDOW_TYPE = 'daily'           # 'daily' or 'demo'

# Daily mode: Windows reset at this time each day
WINDOW_RESET_TIME = "00:00"     # Midnight (format: "HH:MM")

# Demo mode: For live demonstrations (short windows)
DEMO_MODE = True               # Set True for demo
DEMO_WINDOW_SECONDS = 30        # Short windows for demo

# ===== DATABASE CONNECTIONS =====

# Fider's database (READ-ONLY)
FIDER_DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'user': 'fider',
    'password': 'fider123',
    'database': 'fider'
}

# Our DP sidecar database (READ-WRITE)
DP_DB_CONFIG = {
    'host': 'localhost',
    'port': 5433,
    'user': 'dp_user',
    'password': 'dp_password',
    'database': 'dp_sidecar'
}