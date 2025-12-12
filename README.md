# Differential Privacy Sidecar for Fider Voting Platform

A privacy-preserving layer for voting systems that protects individual votes while maintaining utility for decision-making.

**Course Project:** DS593 Privacy-Concious Computer System, Boston University  
**Authors:** Dang Dinh, Yixin Lyu  
**Academic Year:** Fall 2025

---

## 🎯 Overview

This project implements **differential privacy (DP)** for the Fider voting platform to protect voter privacy in small group settings. The system uses a sidecar architecture that wraps Fider with a privacy-preserving layer, replacing exact vote counts with noisy aggregates while tracking privacy budgets.

**Core Innovation:** Noise reuse mechanism that only generates fresh noise when vote counts change, dramatically reducing privacy budget consumption while maintaining protection against averaging attacks.

---

## ❗ Problem Statement

Feature-voting platforms like Fider expose exact, real-time vote counts that reveal individual voting behavior in small groups (15-30 people):

**Example Attack:**
```
12:00 PM - "Ban GenAI" shows: 8 votes
12:05 PM - Alice (known ChatGPT user) clicks upvote
12:06 PM - Count updates to: 9 votes

❌ Everyone knows Alice voted YES
```

**Consequences:**
- Individual votes identifiable through count changes
- Fear of exposure prevents honest feedback
- Timing attacks correlate votes with specific individuals

---

## ✅ Solution

### Three-Layer Privacy Protection

**1. 🔊 Laplace Noise (ε=0.5)**
```
True count: 12 votes → Noisy count: ~14 votes (±4-6 range)
```

**2. ⏰ Fixed Schedule (30-second batches)**
```
Not real-time → Can't identify when someone voted
```

**3. 🔄 Noise Reuse (Budget-Efficient)**
```
Count unchanged → Reuse previous noise (ε=0.0)
Only spend budget when count changes
```

**Privacy Guarantee:** ε-differential privacy where ε ≤ 20.0 (lifetime)

---

## 📁 Project Structure

```
dp-sidecar-project/
├── fider-setup/                 # Fider platform setup
│   └── docker-compose.yaml      # Fider + DB + MailHog
│
├── dp-sidecar/                  # Main project directory
│   ├── src/                     # Source code
│   │   ├── api.py              # FastAPI application
│   │   ├── config.py           # Configuration
│   │   ├── dp_mechanism.py     # Laplace noise generation
│   │   ├── budget_tracker.py   # Budget management
│   │   ├── window_scheduler.py # Batch scheduler
│   │   └── database/
│   │       ├── connections.py  # DB connection helpers
│   │       └── schema.sql      # DP database schema
│   │
│   ├── frontend/               # Dashboard UI
│   │   ├── index.html         # Main page
│   │   ├── css/styles.css     # Styling
│   │   └── js/
│   │       ├── api.js         # API client
│   │       └── app.js         # Application logic
│   │
│   ├── docker-compose.yaml    # DP Sidecar DB
│   └── requirements.txt       # Python dependencies
│
└── README.md                  # This file
```

---

## 🏗️ Architecture

### System Design

```
┌─────────────────────────────────────────────────────┐
│                   USER LAYER                         │
│  ┌──────────┐                    ┌──────────┐      │
│  │  Fider   │  Vote              │Dashboard │      │
│  │  :3000   │                    │  :8080   │      │
│  └────┬─────┘                    └────┬─────┘      │
└───────┼───────────────────────────────┼────────────┘
        │                               │ HTTP GET
┌───────┼───────────────────────────────┼────────────┐
│       │        APPLICATION LAYER      │            │
│       │                               ▼            │
│       │                        ┌──────────┐        │
│       │                        │ FastAPI  │        │
│       │                        │  :8000   │        │
│       │         ┌──────────────┤          │        │
│       │         │              └────┬─────┘        │
│       ▼         ▼                   │              │
│  ┌────────────────┐          ┌─────▼──────┐       │
│  │   Scheduler    │          │  Budget    │       │
│  │ (APScheduler)  │◀─────────│  Tracker   │       │
│  │ • Every 30s    │          └────────────┘       │
│  │ • Gen/reuse    │                               │
│  │   noise        │                               │
│  └────────────────┘                               │
└───────┼───────────────────────────────────────────┘
        │ READ/WRITE
┌───────┼───────────────────────────────────────────┐
│       │            DATA LAYER                     │
│       ▼                                           │
│  ┌──────────┐              ┌──────────┐          │
│  │ Fider DB │              │Sidecar DB│          │
│  │  :5432   │              │  :5433   │          │
│  │          │              │          │          │
│  │• True    │              │• Noisy   │          │
│  │  votes   │              │  counts  │          │
│  │• Exact   │              │• Budgets │          │
│  │  counts  │              │• Windows │          │
│  └──────────┘              └──────────┘          │
└───────────────────────────────────────────────────┘
```

### Key Components

**FastAPI REST API** - Central controller, serves DP counts  
**Batch Scheduler** - Runs every 30s, implements noise logic  
**Budget Tracker** - Tracks lifetime epsilon (cap: 20.0)  
**DP Dashboard** - User interface with budget visualization  

---

## 🌟 Key Features

### Privacy Mechanisms

✅ **Laplace Noise** - Adds noise with scale 1/ε = 2.0  
✅ **Noise Reuse** - Zero epsilon when count unchanged  
✅ **Fixed Schedule** - Prevents timing attacks  
✅ **Lifetime Budget** - Max 20.0 epsilon, ~40 updates  
✅ **Threshold** - Minimum votes before release  

### Utility Features

✅ **Confidence Intervals** - 95% bounds on noisy counts  
✅ **Budget Visualization** - Progress bars, color-coded  
✅ **Auto-Discovery** - Tracks all Fider posts automatically  
✅ **Status Indicators** - Active/Locked/Below threshold  

---

## 🔒 Privacy Guarantees

### Differential Privacy

**Where:** ε = 0.5 per noise generation, Total ε ≤ 20.0

### Attack Resistance

**Averaging Attack:** ❌ Prevented by noise reuse  
**Timing Attack:** ❌ Prevented by fixed schedule  
**Sequential Tracking:** ❌ Prevented by lifetime cap  

---

## 💻 Technology Stack

### Backend
- Python 3.11+, FastAPI, Uvicorn
- NumPy (noise), APScheduler (batch)
- psycopg2, Pydantic

### Database
- PostgreSQL 17 (×2 instances)
- Dual-database architecture

### Frontend
- HTML5, CSS3, JavaScript ES6+
- Fetch API

### Infrastructure
- Docker & Docker Compose
- Fider (Base voting platform)

---

## 📦 Installation

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Git (for cloning)

### Quick Setup

**1. Start Fider:**
```bash
cd fider-setup
docker-compose up -d

# Access: http://localhost:3000
# Create account and posts
```

**2. Start DP Sidecar DB:**
```bash
cd ../dp-sidecar
docker-compose up -d
```

**3. Install Dependencies:**
```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

**4. Test Connections:**
```bash
python -c "from src.database.connections import test_connections; test_connections()"

# Should show:
# ✓ Fider DB connected
# ✓ DP DB connected
```

**5. Start API:**
```bash
uvicorn src.api:app --reload

# Should see:
# 🚀 Scheduler started (DEMO MODE: every 30s)
# ✅ Auto-tracking complete! Tracked X/X posts
```

**6. Start Dashboard (Optional):**
```bash
cd frontend
python -m http.server 8080

# Access: http://localhost:8080
```

---

## 🚀 Usage

### Quick Start

1. **Create posts in Fider** (http://localhost:3000)
2. **Vote on posts** (use incognito windows for multiple users)
3. **Wait 30 seconds** for first scheduler run
4. **View dashboard** (http://localhost:8080)

### API Endpoints

```bash
# Get DP count
curl http://localhost:8000/api/counts/1

# Get budget status
curl http://localhost:8000/api/admin/budget/1

# List tracked posts
curl http://localhost:8000/api/posts

# Health check
curl http://localhost:8000/
```

### Creating Multiple Users

**Incognito Windows:**
```
Chrome (normal) → User 1
Chrome (incognito) → User 2
Firefox → User 3
```

---

## ⚙️ Configuration

### Edit `src/config.py`

```python
# DP Parameters
THRESHOLD = 1                   # Min votes before release
EPSILON_PER_QUERY = 0.5         # Budget per noise generation
LIFETIME_EPSILON_CAP = 20.0     # Max total epsilon

# Schedule
DEMO_MODE = True                # True=30s, False=daily
DEMO_WINDOW_SECONDS = 30        # Demo window duration
WINDOW_RESET_TIME = "00:00"     # Daily reset (production)

# Database
DB_HOST = '127.0.0.1'           # Windows compatibility
```

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `THRESHOLD` | 1 | Minimum votes to release |
| `EPSILON_PER_QUERY` | 0.5 | Privacy budget per release |
| `LIFETIME_EPSILON_CAP` | 20.0 | Max total epsilon |
| `DEMO_MODE` | True | 30s windows vs daily |

---

## 🐛 Troubleshooting

**Database connection failed:**
```bash
# Check Docker
docker ps

# Restart containers
docker-compose down && docker-compose up -d

# Use 127.0.0.1 instead of localhost (Windows)
# Check if the port is using by another program 
```

**Posts not showing:**
```bash
# Wait 30 seconds for scheduler
# Check API logs for auto-tracking
# Hard refresh browser: Ctrl+Shift+R
```

**Scheduler not running:**
```bash
# Check config: DEMO_MODE = True
# Look for "🚀 Scheduler started" in logs
# Restart API
```

---

## 📧 Contact

**Authors:** Dang Dinh, Yixin Lyu  
**Course:** CDSDS293 Privacy-Concious, Fall 2025  
**Institution:** Boston University

---

**Built with ❤️ and 🔒 at Boston University**
