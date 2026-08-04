"""Structured logging with console and file output, plus event callbacks for TUI."""

import logging
import os
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

STATUS_COLORS = {
    "PASS": GREEN,
    "FAIL": RED,
    "WARN": YELLOW,
    "INFO": BLUE,
    "SKIP": CYAN,
}

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class Logger:
    def __init__(self, log_dir="./logs", quiet=False):
        self._callbacks = []
        self._quiet = quiet
        self._log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        log_filename = os.path.join(
            log_dir,
            f"traffic_generator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
        )

        self._file_logger = logging.getLogger("demo_generator.file")
        self._file_logger.setLevel(logging.INFO)
        self._file_logger.propagate = False
        handler = RotatingFileHandler(log_filename, maxBytes=10 * 1024 * 1024, backupCount=5)
        handler.setFormatter(logging.Formatter("%(message)s"))
        self._file_logger.addHandler(handler)

        self._log_filename = log_filename

    @property
    def log_filename(self):
        return self._log_filename

    def subscribe(self, callback):
        self._callbacks.append(callback)

    def _emit(self, entry):
        for cb in self._callbacks:
            try:
                cb(entry)
            except Exception:
                pass

    def log_result(self, category, test_type, target, status, message="", client_name="", round_num=0):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = STATUS_COLORS.get(status, RESET)

        console_line = (
            f"[{timestamp}] {BLUE}{category:18}{RESET} | "
            f"{test_type:12} | {target:50} | "
            f"{color}{status:4}{RESET} {message}"
        )
        if client_name:
            console_line = f"{CYAN}[{client_name:18}]{RESET} " + console_line

        if not self._quiet:
            print(console_line)

        file_line = ANSI_RE.sub("", console_line)
        self._file_logger.info(file_line)

        entry = {
            "timestamp": timestamp,
            "category": category,
            "test_type": test_type,
            "target": target,
            "status": status,
            "message": message,
            "client_name": client_name,
            "round_num": round_num,
        }
        self._emit(entry)

    def info(self, category, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self._quiet:
            console_line = f"[{timestamp}] {YELLOW}>>> {message}{RESET}"
            print(console_line)
        self._file_logger.info(f"[{timestamp}] >>> {message}")
        self._emit({
            "timestamp": timestamp,
            "category": category,
            "test_type": "INFO",
            "target": "",
            "status": "INFO",
            "message": message,
            "client_name": "",
            "round_num": 0,
        })

    def print_summary(self, stats):
        summary = stats.get_cumulative()
        total_pass = summary["total_pass"]
        total_fail = summary["total_fail"]
        total = total_pass + total_fail

        sep = "=" * 100
        print(f"\n{BLUE}{sep}{RESET}")
        print(f"{BLUE}Cumulative Summary ({summary['total_rounds']} rounds){RESET}")
        print(f"{BLUE}{sep}{RESET}\n")

        for cat_name, cat_stats in summary["categories"].items():
            label = f"{cat_name}:"
            print(f"  {label:<25} {GREEN}{cat_stats['pass']} passed{RESET}, {RED}{cat_stats['fail']} failed{RESET}")

        print(f"\n  {'TOTAL:':<25} {GREEN}{total_pass} passed{RESET}, {RED}{total_fail} failed{RESET} out of {total} tests")
        print(f"\n{BLUE}{sep}{RESET}\n")

        self._file_logger.info(f"\n{sep}")
        self._file_logger.info(f"Cumulative Summary ({summary['total_rounds']} rounds)")
        self._file_logger.info(f"{sep}\n")
        for cat_name, cat_stats in summary["categories"].items():
            self._file_logger.info(f"  {cat_name + ':':<25} {cat_stats['pass']} passed, {cat_stats['fail']} failed")
        self._file_logger.info(f"\n  {'TOTAL:':<25} {total_pass} passed, {total_fail} failed out of {total} tests\n")

    def close(self):
        for handler in self._file_logger.handlers[:]:
            handler.close()
            self._file_logger.removeHandler(handler)
