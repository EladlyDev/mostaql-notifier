"""Mostaql Notifier — Configuration Loader.

Loads and validates application configuration from YAML files.
Resolves environment variables referenced via ${VAR_NAME} syntax.
Uses Python dataclasses for type-safe configuration access.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ── Path Constants ────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
PROFILE_PATH = CONFIG_DIR / "my_profile.yaml"

# ── Environment Variable Pattern ─────────────────────────
ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)}")


# ═══════════════════════════════════════════════════════════
# Configuration Dataclasses
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ScraperConfig:
    """Configuration for the web scraper."""

    base_url: str
    projects_url: str
    xhr_endpoint: str
    xhr_headers: dict[str, str]
    scan_interval_seconds: int
    max_pages_per_scan: int
    request_delay_seconds: int
    detail_delay_seconds: int
    max_retries: int
    timeout_seconds: int
    user_agents: list[str]
    categories: list[str]
    proxy_url: str = ""


@dataclass(frozen=True)
class GeminiConfig:
    """Configuration for the Google Gemini AI provider."""

    api_key: str
    model: str
    max_tokens: int
    temperature: float
    rpm_limit: int
    rpd_limit: int


@dataclass(frozen=True)
class GroqConfig:
    """Configuration for the Groq AI provider."""

    api_key: str
    model: str
    max_tokens: int
    temperature: float
    rpm_limit: int


@dataclass(frozen=True)
class AIConfig:
    """Configuration for AI analysis providers."""

    primary_provider: str
    fallback_provider: str
    gemini: GeminiConfig
    groq: GroqConfig


@dataclass(frozen=True)
class TelegramConfig:
    """Configuration for Telegram notifications."""

    bot_token: str
    chat_id: str
    instant_alert_threshold: int
    digest_threshold: int
    digest_interval_minutes: int
    daily_report_hour: int
    daily_report_minute: int


@dataclass(frozen=True)
class ScoringConfig:
    """Configuration for job scoring weights, bonuses, and penalties."""

    weights: dict[str, float]
    bonuses: dict[str, int]
    penalties: dict[str, int]


@dataclass(frozen=True)
class FreelancerProfile:
    """The freelancer's profile used for AI-based job matching."""

    name: str
    skills: dict[str, list[str]]
    experience_years: int
    preferences: dict[str, Any]
    bio: str
    proposal_style: str


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration container."""

    scraper: ScraperConfig
    ai: AIConfig
    telegram: TelegramConfig
    scoring: ScoringConfig
    profile: FreelancerProfile
    database_path: str
    log_level: str


# ═══════════════════════════════════════════════════════════
# YAML Loading & Environment Variable Resolution
# ═══════════════════════════════════════════════════════════


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ${VAR_NAME} references in YAML values.

    Args:
        value: A string, dict, list, or primitive from parsed YAML.

    Returns:
        The same structure with all ${VAR_NAME} placeholders replaced
        by their environment variable values.

    Raises:
        ValueError: If a referenced environment variable is not set.
    """
    if isinstance(value, str):
        matches = ENV_VAR_PATTERN.findall(value)
        for var_name in matches:
            env_value = os.environ.get(var_name)
            if env_value is None:
                raise ValueError(
                    f"Environment variable '${{{var_name}}}' is required but not set. "
                    f"Add it to your .env file or export it in your shell."
                )
            value = value.replace(f"${{{var_name}}}", env_value)
        return value
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load and parse a YAML file with UTF-8 encoding.

    Args:
        path: Absolute or relative path to the YAML file.

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        yaml.YAMLError: If the file contains invalid YAML.
    """
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise ValueError(f"Configuration file is empty: {path}")

    logger.debug("Loaded configuration from %s", path)
    return data


# ═══════════════════════════════════════════════════════════
# Dataclass Builders
# ═══════════════════════════════════════════════════════════


def _build_scraper_config(data: dict[str, Any]) -> ScraperConfig:
    """Build a ScraperConfig from a raw settings dictionary.

    Args:
        data: The 'scraper' section of settings.yaml.

    Returns:
        A validated ScraperConfig instance.
    """
    required_keys = [
        "base_url", "projects_url", "xhr_endpoint", "scan_interval_seconds",
        "max_pages_per_scan", "request_delay_seconds", "max_retries",
        "timeout_seconds", "user_agents",
    ]
    _validate_keys(data, required_keys, "scraper")

    return ScraperConfig(
        base_url=data["base_url"],
        projects_url=data["projects_url"],
        xhr_endpoint=data["xhr_endpoint"],
        xhr_headers=data.get("xhr_headers", {}),
        scan_interval_seconds=data["scan_interval_seconds"],
        max_pages_per_scan=data["max_pages_per_scan"],
        request_delay_seconds=data["request_delay_seconds"],
        detail_delay_seconds=data.get("detail_delay_seconds", 3),
        max_retries=data["max_retries"],
        timeout_seconds=data["timeout_seconds"],
        user_agents=data["user_agents"],
        categories=data.get("categories", []),
    )


def _build_ai_config(data: dict[str, Any]) -> AIConfig:
    """Build an AIConfig from a raw settings dictionary.

    Args:
        data: The 'ai' section of settings.yaml.

    Returns:
        A validated AIConfig instance.
    """
    _validate_keys(data, ["primary_provider", "fallback_provider", "gemini", "groq"], "ai")

    gemini_data = data["gemini"]
    _validate_keys(gemini_data, ["api_key", "model", "max_tokens", "temperature", "rpm_limit"], "ai.gemini")

    groq_data = data["groq"]
    _validate_keys(groq_data, ["api_key", "model", "max_tokens", "temperature", "rpm_limit"], "ai.groq")

    return AIConfig(
        primary_provider=data["primary_provider"],
        fallback_provider=data["fallback_provider"],
        gemini=GeminiConfig(
            api_key=gemini_data["api_key"],
            model=gemini_data["model"],
            max_tokens=gemini_data["max_tokens"],
            temperature=gemini_data["temperature"],
            rpm_limit=gemini_data["rpm_limit"],
            rpd_limit=gemini_data.get("rpd_limit", 1500),
        ),
        groq=GroqConfig(
            api_key=groq_data["api_key"],
            model=groq_data["model"],
            max_tokens=groq_data["max_tokens"],
            temperature=groq_data["temperature"],
            rpm_limit=groq_data["rpm_limit"],
        ),
    )


def _build_telegram_config(data: dict[str, Any]) -> TelegramConfig:
    """Build a TelegramConfig from a raw settings dictionary.

    Args:
        data: The 'telegram' section of settings.yaml.

    Returns:
        A validated TelegramConfig instance.
    """
    required_keys = [
        "bot_token", "chat_id", "instant_alert_threshold",
        "digest_threshold", "digest_interval_minutes",
        "daily_report_hour", "daily_report_minute",
    ]
    _validate_keys(data, required_keys, "telegram")

    return TelegramConfig(
        bot_token=data["bot_token"],
        chat_id=str(data["chat_id"]),
        instant_alert_threshold=data["instant_alert_threshold"],
        digest_threshold=data["digest_threshold"],
        digest_interval_minutes=data["digest_interval_minutes"],
        daily_report_hour=data["daily_report_hour"],
        daily_report_minute=data["daily_report_minute"],
    )


def _build_scoring_config(data: dict[str, Any]) -> ScoringConfig:
    """Build a ScoringConfig from a raw settings dictionary.

    Args:
        data: The 'scoring' section of settings.yaml.

    Returns:
        A validated ScoringConfig instance.

    Raises:
        ValueError: If scoring weights do not sum to 1.0.
    """
    _validate_keys(data, ["weights", "bonuses", "penalties"], "scoring")

    weights = data["weights"]
    total = sum(weights.values())
    if not (0.99 <= total <= 1.01):
        raise ValueError(
            f"Scoring weights must sum to 1.0, got {total:.4f}. "
            f"Current weights: {weights}"
        )

    return ScoringConfig(
        weights=weights,
        bonuses=data["bonuses"],
        penalties=data["penalties"],
    )


def _build_profile(data: dict[str, Any]) -> FreelancerProfile:
    """Build a FreelancerProfile from a raw profile dictionary.

    Args:
        data: The parsed my_profile.yaml content.

    Returns:
        A validated FreelancerProfile instance.
    """
    _validate_keys(data, ["name", "skills", "experience_years", "preferences", "bio"], "profile")

    return FreelancerProfile(
        name=data["name"],
        skills=data["skills"],
        experience_years=data["experience_years"],
        preferences=data["preferences"],
        bio=data["bio"],
        proposal_style=data.get("proposal_style", ""),
    )


def _validate_keys(data: dict[str, Any], required: list[str], section: str) -> None:
    """Validate that all required keys exist in a config section.

    Args:
        data: The configuration dictionary to validate.
        required: List of required key names.
        section: Human-readable section name for error messages.

    Raises:
        ValueError: If any required key is missing.
    """
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(
            f"Missing required configuration keys in '{section}': {', '.join(missing)}"
        )


# ═══════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════


def load_config(
    settings_path: Path | None = None,
    profile_path: Path | None = None,
    env_path: Path | None = None,
) -> AppConfig:
    """Load the complete application configuration.

    Loads settings.yaml and my_profile.yaml, resolves environment variables,
    validates all required fields, and returns a typed AppConfig instance.

    Args:
        settings_path: Override path to settings.yaml. Defaults to config/settings.yaml.
        profile_path: Override path to my_profile.yaml. Defaults to config/my_profile.yaml.
        env_path: Override path to .env file. Defaults to project root .env.

    Returns:
        A fully validated AppConfig instance.

    Raises:
        FileNotFoundError: If a config file is missing.
        ValueError: If required fields are missing or env vars are unset.
    """
    # Load environment variables from .env
    env_file = env_path or (PROJECT_ROOT / ".env")
    load_dotenv(env_file)
    logger.debug("Loaded environment from %s", env_file)

    # Load and resolve YAML files
    settings_file = settings_path or SETTINGS_PATH
    profile_file = profile_path or PROFILE_PATH

    raw_settings = _load_yaml(settings_file)
    raw_profile = _load_yaml(profile_file)

    # Resolve environment variables
    settings = _resolve_env_vars(raw_settings)
    profile = _resolve_env_vars(raw_profile)

    # Validate top-level sections
    _validate_keys(settings, ["scraper", "ai", "telegram", "scoring", "database", "logging"], "settings")

    # Build typed configuration
    config = AppConfig(
        scraper=_build_scraper_config(settings["scraper"]),
        ai=_build_ai_config(settings["ai"]),
        telegram=_build_telegram_config(settings["telegram"]),
        scoring=_build_scoring_config(settings["scoring"]),
        profile=_build_profile(profile),
        database_path=settings["database"]["path"],
        log_level=settings["logging"]["level"],
    )

    logger.info("Configuration loaded successfully")
    logger.debug("Database path: %s", config.database_path)
    logger.debug("AI primary provider: %s", config.ai.primary_provider)
    logger.debug("Telegram alert threshold: %d", config.telegram.instant_alert_threshold)

    return config
