# Mostaql Notifier

> Continuously scrapes freelancing jobs from [mostaql.com](https://mostaql.com), analyzes them with AI, scores them, and sends Telegram notifications for high-quality opportunities.

## 📁 Project Structure

```
mostaql-notifier/
├── config/
│   ├── settings.yaml          # App settings (scraper, AI, telegram, scoring)
│   └── my_profile.yaml        # Freelancer profile for AI matching
├── src/
│   ├── main.py                # Entry point
│   ├── config.py              # Configuration loader
│   ├── database/              # SQLite persistence layer
│   │   ├── models.py          # Data entities (Job, Analysis, Score, etc.)
│   │   ├── db.py              # Async connection manager
│   │   └── queries.py         # All DB operations
│   ├── scraper/               # Web scraping (future)
│   ├── analyzer/              # AI analysis (future)
│   ├── scorer/                # Scoring logic (future)
│   ├── notifier/              # Telegram notifications (future)
│   └── utils/
│       ├── logger.py          # Colored console + rotating file logging
│       └── rate_limiter.py    # Async token-bucket rate limiter
├── scripts/
│   └── test_foundation.py     # Foundation verification script
├── data/                      # SQLite database
├── logs/                      # Log files
├── .env                       # Environment variables (secrets)
├── .env.example               # Template for required env vars
└── requirements.txt           # Python dependencies
```

## 🚀 Getting Started

### Prerequisites
- Python 3.11+

### Installation

```bash
# Clone and enter the project
cd mostaql-notifier

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env with your actual API keys and tokens
```

### Configuration

1. **Edit `.env`** — Add your API keys (Gemini, Groq) and Telegram bot credentials
2. **Edit `config/my_profile.yaml`** — Customize your freelancer profile for AI matching
3. **Review `config/settings.yaml`** — Adjust scraper intervals, scoring weights, etc.

### Run

```bash
# Test the foundation
python scripts/test_foundation.py

# Start the notifier (once all modules are implemented)
python -m src.main
```

## 🔧 Tech Stack

| Component | Library |
|-----------|---------|
| HTTP Client | `httpx` |
| HTML Parsing | `selectolax` |
| Database | `aiosqlite` (SQLite) |
| Telegram Bot | `python-telegram-bot` v21+ |
| Scheduling | `apscheduler` |
| Config | `pyyaml` + `python-dotenv` |

## 📝 License

Private project — not for distribution.
