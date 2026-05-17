"""Prometheus metrics definitions.

Import and increment from anywhere; expose via GET /metrics.
All metrics prefixed `supersahayak_`.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, REGISTRY

# ── Notifications ─────────────────────────────────────────────────────────────

notifications_sent = Counter(
    "supersahayak_notifications_sent_total",
    "Total notifications sent",
    ["channel", "type"],
)

notifications_failed = Counter(
    "supersahayak_notifications_failed_total",
    "Total notification send failures",
    ["channel", "error_type"],
)

# ── Scraper ───────────────────────────────────────────────────────────────────

scraper_requests = Counter(
    "supersahayak_scraper_requests_total",
    "Total scraper HTTP requests",
    ["domain", "status_code"],
)

scraper_429s = Counter(
    "supersahayak_scraper_429_total",
    "Total 429 responses received by scraper",
    ["domain"],
)

# ── Case search ───────────────────────────────────────────────────────────────

case_search_duration = Histogram(
    "supersahayak_case_search_duration_seconds",
    "Case search endpoint latency",
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0],
)

# ── Display board ─────────────────────────────────────────────────────────────

display_board_poll_duration = Histogram(
    "supersahayak_display_board_poll_duration_seconds",
    "Display board poll cycle latency",
    buckets=[1.0, 5.0, 10.0, 20.0, 30.0],
)

# ── Queue ─────────────────────────────────────────────────────────────────────

queue_depth = Gauge(
    "supersahayak_queue_depth",
    "Current depth of a named queue",
    ["queue_name"],
)

# ── VC links ──────────────────────────────────────────────────────────────────

vc_link_unverified = Gauge(
    "supersahayak_vc_link_unverified_total",
    "Number of VC links that are unverified or stale (>7 days)",
)

reconciliation_confidence = Counter(
    "supersahayak_reconciliation_confidence_total",
    "Reconciliation results by confidence level",
    ["level"],
)
