"""Application metrics collection."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class MetricCounter:
    name: str
    value: int = 0
    labels: dict[str, str] = field(default_factory=dict)


class MetricsRegistry:
    """In-process metrics registry for operational monitoring."""

    _instance: MetricsRegistry | None = None
    _lock = Lock()

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}

    @classmethod
    def get_instance(cls) -> MetricsRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def increment(self, name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        self._histograms[key].append(value)
        if len(self._histograms[key]) > 10000:
            self._histograms[key] = self._histograms[key][-5000:]

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._key(name, labels)
        self._gauges[key] = value

    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        return self._counters.get(self._key(name, labels), 0)

    def get_histogram_stats(self, name: str, labels: dict[str, str] | None = None) -> dict[str, float]:
        values = self._histograms.get(self._key(name, labels), [])
        if not values:
            return {"count": 0, "avg": 0, "p95": 0, "max": 0}
        sorted_vals = sorted(values)
        p95_idx = int(len(sorted_vals) * 0.95)
        return {
            "count": len(values),
            "avg": sum(values) / len(values),
            "p95": sorted_vals[min(p95_idx, len(sorted_vals) - 1)],
            "max": max(values),
        }

    def export_prometheus(self) -> str:
        lines = []
        for key, value in self._counters.items():
            lines.append(f"# TYPE {key.split('{')[0]} counter")
            lines.append(f"{key} {value}")
        for key, value in self._gauges.items():
            lines.append(f"# TYPE {key.split('{')[0]} gauge")
            lines.append(f"{key} {value}")
        return "\n".join(lines)

    @staticmethod
    def _key(name: str, labels: dict[str, str] | None) -> str:
        if not labels:
            return name
        label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


class Timer:
    """Context manager for timing operations."""

    def __init__(self, metric_name: str, labels: dict[str, str] | None = None) -> None:
        self.metric_name = metric_name
        self.labels = labels
        self.registry = MetricsRegistry.get_instance()
        self._start: float = 0

    def __enter__(self) -> Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: object) -> None:
        elapsed = (time.monotonic() - self._start) * 1000
        self.registry.observe(self.metric_name, elapsed, self.labels)
