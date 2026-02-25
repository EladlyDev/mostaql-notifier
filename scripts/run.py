#!/usr/bin/env python3
"""Mostaql Notifier — Application Runner.

Performs pre-flight checks and launches the main application.

Usage:
    python scripts/run.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BANNER = r"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ███╗   ███╗ ██████╗ ███████╗████████╗ █████╗           ║
║   ████╗ ████║██╔═══██╗██╔════╝╚══██╔══╝██╔══██╗          ║
║   ██╔████╔██║██║   ██║███████╗   ██║   ███████║          ║
║   ██║╚██╔╝██║██║   ██║╚════██║   ██║   ██╔══██║          ║
║   ██║ ╚═╝ ██║╚██████╔╝███████║   ██║   ██║  ██║          ║
║   ╚═╝     ╚═╝ ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝          ║
║                                                          ║
║              Mostaql Notifier v1.0                       ║
║         Smart Freelance Job Monitoring                   ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""

REQUIRED_ENV_VARS = [
    "GEMINI_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
]

REQUIRED_FILES = [
    "config/settings.yaml",
    "config/my_profile.yaml",
]


def preflight_checks() -> bool:
    """Run pre-flight checks before starting the application.

    Checks:
      - .env file exists
      - Required environment variables are set
      - Required config files exist
      - data/ and logs/ directories exist (creates them)

    Returns:
        True if all checks pass, False otherwise.
    """
    os.chdir(str(PROJECT_ROOT))
    ok = True

    # Load .env
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        print("❌ .env file not found!")
        print("   Copy .env.example to .env and fill in your API keys.")
        ok = False
    else:
        from dotenv import load_dotenv
        load_dotenv(env_path)
        print("✅ .env loaded")

    # Check required env vars
    for var in REQUIRED_ENV_VARS:
        val = os.environ.get(var, "")
        if not val or val in ("your_key_here", "test", ""):
            print(f"❌ {var} not set or invalid in .env")
            ok = False
        else:
            # Mask the value
            masked = val[:6] + "..." + val[-4:] if len(val) > 10 else "***"
            print(f"✅ {var} = {masked}")

    # GROQ_API_KEY is optional (fallback provider)
    groq = os.environ.get("GROQ_API_KEY", "")
    if groq and groq not in ("your_key_here", "test"):
        print(f"✅ GROQ_API_KEY = {groq[:6]}...{groq[-4:]}")
    else:
        print("⚠️  GROQ_API_KEY not set (fallback AI will be unavailable)")

    # Check config files
    for f in REQUIRED_FILES:
        path = PROJECT_ROOT / f
        if not path.exists():
            print(f"❌ {f} not found!")
            ok = False
        else:
            print(f"✅ {f} exists")

    # Create directories
    for d in ("data", "logs"):
        (PROJECT_ROOT / d).mkdir(exist_ok=True)
        print(f"✅ {d}/ directory ready")

    return ok


def main() -> None:
    """Entry point: run checks then start the application."""
    print(BANNER)

    print("═══ Pre-flight Checks ═══\n")
    if not preflight_checks():
        print("\n❌ Pre-flight checks failed! Fix the issues above and try again.")
        sys.exit(1)

    print("\n✅ All checks passed!\n")
    print("═══ Starting Mostaql Notifier ═══\n")

    from src.main import main as app_main
    app_main()


if __name__ == "__main__":
    main()
