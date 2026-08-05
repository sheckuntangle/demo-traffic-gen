"""Per-round and cumulative statistics tracking."""

import threading
from collections import defaultdict


class Stats:
    def __init__(self):
        self._lock = threading.Lock()
        self._round_stats = defaultdict(lambda: {"pass": 0, "fail": 0})
        self._cumulative = defaultdict(lambda: {"pass": 0, "fail": 0})
        self._total_rounds = 0

    def record(self, category, success):
        key = "pass" if success else "fail"
        with self._lock:
            self._round_stats[category][key] += 1
            self._cumulative[category][key] += 1

    def finish_round(self):
        with self._lock:
            self._total_rounds += 1
            summary = self._get_round_summary_unlocked()
            self._round_stats.clear()
            return summary

    def _get_round_summary_unlocked(self):
        total_pass = sum(s["pass"] for s in self._round_stats.values())
        total_fail = sum(s["fail"] for s in self._round_stats.values())
        return {
            "round_num": self._total_rounds,
            "total_pass": total_pass,
            "total_fail": total_fail,
            "categories": dict(self._round_stats),
        }

    def reset_category(self, category):
        with self._lock:
            self._cumulative[category] = {"pass": 0, "fail": 0}
            self._round_stats[category] = {"pass": 0, "fail": 0}

    def get_round_summary(self):
        with self._lock:
            return self._get_round_summary_unlocked()

    def get_cumulative(self):
        with self._lock:
            total_pass = sum(s["pass"] for s in self._cumulative.values())
            total_fail = sum(s["fail"] for s in self._cumulative.values())
            return {
                "total_rounds": self._total_rounds,
                "total_pass": total_pass,
                "total_fail": total_fail,
                "categories": dict(self._cumulative),
            }
