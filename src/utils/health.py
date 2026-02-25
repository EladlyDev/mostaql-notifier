"""Mostaql Notifier — Health Monitoring.

Tracks system health metrics for monitoring and alerting.
Uses in-memory data structures (deque) for bounded event history
with zero DB overhead.

Usage:
    monitor = HealthMonitor()
    monitor.record_cycle({"duration": 5.0, "new_jobs": 10, "errors": 0})
    status = monitor.get_status()
    alert = monitor.should_alert(circuit_breakers=[cb1, cb2])
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _CycleRecord:
    """Record of a single scan cycle."""
    timestamp: float
    duration: float
    new_jobs: int
    analyzed: int
    alerts_sent: int
    errors: int


@dataclass
class _ErrorRecord:
    """Record of a single error event."""
    timestamp: float
    component: str
    error: str


class HealthMonitor:
    """Tracks system health metrics for monitoring and alerting.

    All data is in-memory with bounded history (deque). No DB overhead.
    Designed for a 1GB VPS — memory footprint is minimal.

    Attributes:
        start_time: When the monitor was created (app start).
    """

    def __init__(self, max_history: int = 200) -> None:
        """Initialize the health monitor.

        Args:
            max_history: Maximum number of cycle/error records to keep.
        """
        self.start_time = time.monotonic()
        self._start_datetime = datetime.now()

        # Bounded history
        self._cycles: deque[_CycleRecord] = deque(maxlen=max_history)
        self._errors: deque[_ErrorRecord] = deque(maxlen=max_history)

        # Aggregate counters (never reset)
        self.total_cycles = 0
        self.total_jobs = 0
        self.total_analyzed = 0
        self.total_alerts = 0
        self.total_errors = 0
        self.total_tokens = 0

        # Last cycle info
        self.last_cycle_time: Optional[float] = None
        self.last_cycle_duration: float = 0.0

    def record_cycle(self, stats: dict[str, Any]) -> None:
        """Record stats from a completed scan cycle.

        Args:
            stats: Dict with keys: duration, new_jobs, analyzed,
                   alerts_sent, errors, tokens_used.
        """
        now = time.monotonic()
        record = _CycleRecord(
            timestamp=now,
            duration=stats.get("duration", 0.0),
            new_jobs=stats.get("new_jobs", 0),
            analyzed=stats.get("analyzed", 0),
            alerts_sent=stats.get("alerts_sent", 0),
            errors=stats.get("errors", 0),
        )
        self._cycles.append(record)

        # Update aggregates
        self.total_cycles += 1
        self.total_jobs += record.new_jobs
        self.total_analyzed += record.analyzed
        self.total_alerts += record.alerts_sent
        self.total_errors += record.errors
        self.total_tokens += stats.get("tokens_used", 0)

        self.last_cycle_time = now
        self.last_cycle_duration = record.duration

        if self.total_cycles % 10 == 0:
            self._log_memory()

    def record_error(self, component: str, error: str) -> None:
        """Record an error event.

        Args:
            component: Component name (scraper, gemini, groq, telegram).
            error: Error description.
        """
        self._errors.append(_ErrorRecord(
            timestamp=time.monotonic(),
            component=component,
            error=error[:200],
        ))
        logger.debug("Health: error recorded for %s", component)

    def get_status(self) -> dict[str, Any]:
        """Get current system health status.

        Returns:
            Dict with uptime, totals, error rate, memory, averages.
        """
        now = time.monotonic()
        uptime_s = now - self.start_time

        # Error rate in last hour
        one_hour_ago = now - 3600
        recent_errors = sum(
            1 for e in self._errors if e.timestamp > one_hour_ago
        )
        recent_cycles = sum(
            1 for c in self._cycles if c.timestamp > one_hour_ago
        )
        error_rate = (
            recent_errors / max(recent_cycles, 1) * 100
            if recent_cycles > 0 else 0.0
        )

        # Average cycle duration (last 20)
        recent_durations = [
            c.duration for c in list(self._cycles)[-20:]
        ]
        avg_duration = (
            sum(recent_durations) / len(recent_durations)
            if recent_durations else 0.0
        )

        # Time since last cycle
        since_last = (
            now - self.last_cycle_time if self.last_cycle_time else None
        )

        # Memory usage
        memory_mb = self._get_memory_mb()

        return {
            "uptime": self._format_uptime(uptime_s),
            "uptime_seconds": uptime_s,
            "started_at": self._start_datetime.strftime("%Y-%m-%d %H:%M"),
            "total_cycles": self.total_cycles,
            "total_jobs": self.total_jobs,
            "total_analyzed": self.total_analyzed,
            "total_alerts": self.total_alerts,
            "total_errors": self.total_errors,
            "total_tokens": self.total_tokens,
            "error_rate_1h": round(error_rate, 1),
            "recent_errors_1h": recent_errors,
            "avg_cycle_duration": round(avg_duration, 1),
            "last_cycle_duration": round(self.last_cycle_duration, 1),
            "seconds_since_last_cycle": round(since_last, 0) if since_last else None,
            "memory_mb": memory_mb,
        }

    def should_alert(
        self,
        circuit_breakers: Optional[list] = None,
    ) -> Optional[str]:
        """Check if any condition warrants a Telegram alert.

        Args:
            circuit_breakers: List of CircuitBreaker instances to check.

        Returns:
            Alert message string, or None if everything is fine.
        """
        now = time.monotonic()
        alerts: list[str] = []

        # Error rate > 50% in last hour
        one_hour_ago = now - 3600
        recent_errors = sum(
            1 for e in self._errors if e.timestamp > one_hour_ago
        )
        recent_cycles = sum(
            1 for c in self._cycles if c.timestamp > one_hour_ago
        )
        if recent_cycles >= 3 and recent_errors / max(recent_cycles, 1) > 0.5:
            alerts.append(
                f"معدل الأخطاء مرتفع: {recent_errors}/{recent_cycles} "
                f"({recent_errors/recent_cycles*100:.0f}%)"
            )

        # No successful cycle in 30 minutes
        if self.last_cycle_time:
            since_last = now - self.last_cycle_time
            if since_last > 1800 and self.total_cycles > 0:
                mins = int(since_last / 60)
                alerts.append(f"لم يتم فحص ناجح منذ {mins} دقيقة")

        # Memory > 800MB
        memory_mb = self._get_memory_mb()
        if memory_mb > 800:
            alerts.append(f"استخدام ذاكرة مرتفع: {memory_mb:.0f}MB")

        # Circuit breakers
        if circuit_breakers:
            for cb in circuit_breakers:
                if cb.state == "OPEN" and not cb.has_alerted:
                    alerts.append(f"خدمة {cb.name} غير متاحة")
                    cb.mark_alerted()

        if not alerts:
            return None

        return "⚠️ تنبيه النظام:\n" + "\n".join(f"• {a}" for a in alerts)

    def _get_memory_mb(self) -> float:
        """Get current process RSS memory in MB."""
        try:
            # /proc/self/status is most reliable on Linux
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024  # kB → MB
        except (FileNotFoundError, ValueError, IndexError):
            pass

        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_maxrss / 1024  # kB → MB on Linux
        except (ImportError, AttributeError):
            return 0.0

        return 0.0

    def _log_memory(self) -> None:
        """Log current memory usage."""
        mb = self._get_memory_mb()
        logger.info(
            "Health check [cycle %d]: RSS=%.1fMB, errors_1h=%d, "
            "total_jobs=%d, total_analyzed=%d",
            self.total_cycles, mb,
            sum(1 for e in self._errors
                if e.timestamp > time.monotonic() - 3600),
            self.total_jobs, self.total_analyzed,
        )

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        """Format seconds into human-readable uptime."""
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        if hours >= 24:
            days = hours // 24
            hours = hours % 24
            return f"{days}d {hours}h {mins}m"
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"
