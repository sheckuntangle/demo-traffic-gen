"""Singleton managing Engine lifecycle, config persistence, and WebSocket broadcasting."""

import asyncio
import copy
import json
import os
import random
import tempfile
import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

from ..config import SCHEDULER_DEFAULTS
from ..engine import Engine, RunMode
from ..logger import Logger
from ..stats import Stats
from ..scheduling import next_daily_run
from ..clients import ClientPool


class RunConflict(RuntimeError):
    """Another test owns the shared runner."""


class RunManager:
    def __init__(self, config, config_path):
        self.config = config
        self.config.setdefault("scheduler", copy.deepcopy(SCHEDULER_DEFAULTS))
        self._scheduler_task = None
        self._scheduler_waiting = False
        self._scheduled_tests = None
        self.config_path = config_path
        self.logger = Logger(
            log_dir=config["generator"].get("log_dir", "./logs"),
            quiet=True,
        )
        self.stats = Stats()
        self._pool = ClientPool(config)
        self._docker_pool = None
        self._engine = None
        self._run_task = None
        self._single_run_task = None
        self._mode = None
        self._start_time = None
        self.ws_clients = set()
        self._active_category = None
        self._phase = "idle"
        self._history = deque(maxlen=10000)
        history_path = os.path.join(config["generator"].get("log_dir", "./logs"), "web_history.jsonl")
        for path in (history_path + ".1", history_path):
            try:
                with open(path) as history:
                    for line in history:
                        try:
                            entry = json.loads(line)
                            if isinstance(entry, dict):
                                # Older history used the controller's local wall time
                                # without an offset. Attach its timezone before replay.
                                if entry.get("timestamp"):
                                    try:
                                        stamp = datetime.fromisoformat(entry["timestamp"])
                                        entry["timestamp"] = stamp.astimezone().isoformat(timespec="seconds")
                                    except (ValueError, TypeError):
                                        pass
                                self._history.append(entry)
                        except ValueError:
                            pass
            except FileNotFoundError:
                pass
        self._history_handler = RotatingFileHandler(
            history_path, maxBytes=10 * 1024 * 1024, backupCount=1)
        self._history_handler.setFormatter(logging.Formatter("%(message)s"))

        self.logger.subscribe(self._on_log_entry)

    def _on_log_entry(self, entry):
        self._history.append(entry)
        self._history_handler.emit(logging.LogRecord(
            "web_history", logging.INFO, "", 0, json.dumps(entry), (), None))
        self.broadcast({"type": "log", "data": entry})

    def broadcast(self, message):
        dead = set()
        for ws in self.ws_clients:
            try:
                asyncio.ensure_future(self._safe_send(ws, message, dead))
            except Exception:
                dead.add(ws)
        self.ws_clients -= dead

    async def _safe_send(self, ws, message, dead):
        try:
            await asyncio.wait_for(ws.send_json(message), timeout=5)
        except Exception:
            dead.add(ws)
            self.ws_clients.discard(ws)

    def get_status(self):
        running = self._phase != "idle"
        elapsed = int((datetime.now(timezone.utc) - self._start_time).total_seconds()) if running and self._start_time else 0
        return {
            "running": running,
            "phase": self._phase,
            "category": self._active_category,
            "mode": "scheduled" if self._scheduled_tests is not None else (self._mode.value if self._mode else None),
            "round": self._engine.round_num if self._engine else 0,
            "elapsed_seconds": elapsed,
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "log_file": self.logger.log_filename,
        }

    def get_log_history(self):
        return list(self._history)

    def delete_logs(self):
        deleted = self.logger.delete_logs()
        self.logger.truncate_handler(self._history_handler)
        backup = self._history_handler.baseFilename + ".1"
        try:
            os.unlink(backup)
            deleted += 1
        except FileNotFoundError:
            pass
        self._history.clear()
        self.broadcast({"type": "logs_deleted"})
        return deleted + 1  # Includes the active shared history file.

    def _publish_status(self):
        self.broadcast({"type": "status", "data": self.get_status()})

    def _reserve(self, mode=None, category=None):
        # No await between checking and reserving: concurrent HTTP requests cannot overlap.
        if self._phase != "idle":
            raise RunConflict("A test is already in progress. Wait for it to complete or stop it first.")
        self._scheduled_tests = None
        self._mode = mode
        self._active_category = category
        self._phase = "starting"
        self._start_time = datetime.now(timezone.utc)
        self._engine = None
        self._publish_status()

    def get_stats(self):
        return self.stats.get_cumulative()

    async def _get_active_pool(self):
        if self.config.get("docker", {}).get("enabled"):
            pool = self.get_docker_pool()
            if not pool.is_started:
                self.logger.info("SYSTEM", "Starting Docker containers...")
                await pool.start()
            return pool
        return self._pool

    async def start(self, mode="full"):
        self._reserve(mode=RunMode(mode))
        self._run_task = asyncio.create_task(self._execute_run())

    async def _execute_run(self, category=None, scheduled_tests=None, run_count=1, scheduled_settings=None):
        outcome = "completed"
        began = datetime.now(timezone.utc)
        try:
            run_config = copy.deepcopy(self.config) if scheduled_tests is not None else self.config
            timed = scheduled_tests is not None and (scheduled_settings or {}).get("execution_mode") == "duration"
            if timed:
                for name, settings in run_config.get("categories", {}).items():
                    settings["enabled"] = name in scheduled_tests
                run_config["generator"]["max_rounds"] = 0
                self.logger.info("SCHEDULER", f"Duration mode: {scheduled_settings['duration_minutes']} minutes after client startup; "
                    f"legitimate interval={run_config['generator'].get('legitimate_interval_seconds', 45)}s; "
                    f"trigger interval={run_config['generator']['round_interval_seconds']}s (also delays first trigger); "
                    f"selected={', '.join(scheduled_tests)}; counts, shuffle and max rounds do not apply.")
            pool = await self._get_active_pool()
            self._engine = Engine(run_config, self.logger, self.stats, pool=pool)
            self._engine.on("on_round_start", lambda **kw: self.broadcast({
                "type": "round_start", "data": kw
            }))
            self._engine.on("on_round_complete", lambda **kw: self.broadcast({
                "type": "round_complete", "data": kw
            }))
            self._engine.on("on_test_complete", lambda **kw: self.broadcast({
                "type": "stats", "data": self.get_stats()
            }))
            self._phase = "running"
            self._publish_status()
            if scheduled_tests is not None:
                for name in set(scheduled_tests):
                    self.stats.reset_category(name)
                if timed:
                    await self._engine.run_timed(scheduled_settings["duration_minutes"] * 60, scheduled_tests)
                    outcome = "duration reached"
                else:
                    for index, name in enumerate(scheduled_tests, 1):
                        self.logger.info("SCHEDULER", f"Scheduled run {index}/{len(scheduled_tests)}: {name}")
                        self._active_category = name
                        self._publish_status()
                        await self._engine.run_single_category(name, reset_stats=False)
                self.logger.info("SCHEDULER", "Scheduled tests completed.")
            elif category:
                self.stats.reset_category(category)
                for index in range(1, run_count + 1):
                    self.logger.info("SYSTEM", f"Manual run {index}/{run_count}: {category}")
                    await self._engine.run_single_category(category, reset_stats=False)
            else:
                await self._engine.start(mode=self._mode)
        except asyncio.CancelledError:
            outcome = "stopped by user/controller"
            self.logger.info("SYSTEM", "Test stopped.")
        except Exception as e:
            outcome = f"error: {type(e).__name__}: {e}"
            self.logger.info("ERROR", f"Test error: {type(e).__name__}: {e}")
        finally:
            if outcome == "completed" and self._phase == "stopping":
                outcome = "stopped by user/controller"
            self._phase = "stopping"
            self._publish_status()
            try:
                if self._docker_pool:
                    await self._docker_pool.cleanup()
            finally:
                label = "SCHEDULE SUMMARY" if scheduled_tests is not None else "RUN SUMMARY"
                self.logger.info(label, f"Run finished: {outcome}; started={began.isoformat()}; "
                    f"elapsed={(datetime.now(timezone.utc) - began).total_seconds():.1f}s including startup and cleanup")
                if scheduled_tests is not None:
                    self.logger.info(label, f"Next daily run: {self.config['scheduler'].get('scheduled_at') if self.config['scheduler'].get('enabled') else 'disabled'}")
                if self._engine:
                    self._engine.log_summary(label, outcome)
                else:
                    self.logger.info(label, f"No tests started; {outcome}; check client startup logs.")
                self._phase = "idle"
                self._active_category = None
                self._scheduled_tests = None
                self.broadcast({"type": "stats", "data": self.get_stats()})
                self._publish_status()

    async def stop(self):
        task = next((t for t in (self._single_run_task, self._run_task)
                     if t is not None and not t.done()), None)
        if task and not task.done():
            if self._phase == "stopping":
                await asyncio.shield(task)
                return
            # Let a newly created task enter its try/finally before cancelling it.
            await asyncio.sleep(0)
            if task.done():
                return
            if self._phase == "stopping":
                await asyncio.shield(task)
                return
            self._phase = "stopping"
            self._publish_status()
            if self._engine:
                self._engine.request_stop()
            task.cancel()
            await task

    async def run_single(self, category_name, run_count=1):
        from ..categories import get_category
        if get_category(category_name) is None:
            raise ValueError(f"Unknown category: {category_name}")
        if type(run_count) is not int or not 1 <= run_count <= 1000:
            raise ValueError("Run count must be a whole number from 1 to 1000")
        self._reserve(category=category_name)
        self._single_run_task = asyncio.create_task(self._execute_run(category_name, run_count=run_count))

    async def stop_single(self):
        if self._active_category:
            await self.stop()

    def start_scheduler(self):
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    def update_scheduler(self, data):
        if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
            raise ValueError("Scheduler enabled must be true or false")
        tests = data.get("tests")
        allowed = set(SCHEDULER_DEFAULTS["tests"])
        if (not isinstance(tests, dict) or set(tests) - allowed
                or any(type(value) is not bool for value in tests.values())):
            raise ValueError("Scheduler tests must contain known tests with boolean switches")
        frequency = data.get("frequency", "once")
        execution_mode = data.get("execution_mode", "counts")
        duration_minutes = data.get("duration_minutes", 60)
        if execution_mode not in ("counts", "duration"):
            raise ValueError("Execution mode must be counts or duration")
        if type(duration_minutes) is not int or not 1 <= duration_minutes <= 1440:
            raise ValueError("Duration must be a whole number from 1 to 1440 minutes")
        run_counts = data.get("run_counts", {})
        if (not isinstance(run_counts, dict) or set(run_counts) - allowed
                or any(type(count) is not int or not 1 <= count <= 1000 for count in run_counts.values())):
            raise ValueError("Run counts must be whole numbers from 1 to 1000 for known tests")
        randomize_order = data.get("randomize_order", False)
        if type(randomize_order) is not bool:
            raise ValueError("Randomize order must be true or false")
        if frequency not in ("once", "daily"):
            raise ValueError("Frequency must be once or daily")
        daily_time = data.get("daily_time", "15:00")
        zone = data.get("timezone", "UTC")
        scheduled_at = data.get("scheduled_at")
        if frequency == "daily":
            scheduled_at = next_daily_run(daily_time, zone, datetime.now(timezone.utc)).isoformat()
        if scheduled_at:
            try:
                when = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
                if when.tzinfo is None or when.utcoffset() is None:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Scheduled time must include a timezone")
            scheduled_at = when.astimezone(timezone.utc).isoformat()
        if data["enabled"]:
            if not scheduled_at or when <= datetime.now(timezone.utc):
                raise ValueError("Choose a future date and time")
            if not any(tests.values()):
                raise ValueError("Select at least one test")
        schedule = {"enabled": data["enabled"], "scheduled_at": scheduled_at,
                    "execution_mode": execution_mode, "duration_minutes": duration_minutes,
                    "run_counts": {name: run_counts.get(name, 1) for name in SCHEDULER_DEFAULTS["tests"]},
                    "randomize_order": randomize_order,
                    "frequency": frequency, "daily_time": daily_time, "timezone": zone,
                    "tests": {name: tests.get(name, False) for name in SCHEDULER_DEFAULTS["tests"]}}
        previous = self.config["scheduler"]
        self.config["scheduler"] = schedule
        try:
            self._save_config()
        except Exception:
            self.config["scheduler"] = previous
            raise
        self._scheduler_waiting = False
        self.broadcast({"type": "scheduler", "data": schedule})
        self.logger.info("SCHEDULER", f"Scheduled tests for {scheduled_at}" if schedule["enabled"] else "Scheduler disabled.")
        return schedule

    async def _check_schedule(self, now=None):
        schedule = self.config["scheduler"]
        if not schedule.get("enabled"):
            return
        when = datetime.fromisoformat(schedule["scheduled_at"].replace("Z", "+00:00"))
        now = now or datetime.now(timezone.utc)
        if now < when:
            return
        if self._phase != "idle":
            if not self._scheduler_waiting:
                self.logger.info("SCHEDULER", "Scheduled time reached; waiting for the active test to finish.")
                self._scheduler_waiting = True
            return  # Wait for the active test; never overlap runs.
        timed = schedule.get("execution_mode") == "duration"
        tests = [name for name in SCHEDULER_DEFAULTS["tests"] if schedule["tests"].get(name)
                 for _ in range(1 if timed else schedule.get("run_counts", {}).get(name, 1))]
        if not timed and schedule.get("randomize_order", False):
            random.shuffle(tests)
        # Persist consumption before dispatch so a controller restart cannot repeat it.
        previous = copy.deepcopy(schedule)
        if schedule.get("frequency", "once") == "daily":
            schedule["scheduled_at"] = next_daily_run(
                schedule["daily_time"], schedule["timezone"], now).isoformat()
        else:
            schedule["enabled"] = False
        schedule["last_run_at"] = now.isoformat()
        try:
            self._save_config()
        except Exception:
            self.config["scheduler"] = previous
            raise
        self._scheduler_waiting = False
        self._reserve()
        self._scheduled_tests = tests
        self.logger.info("SCHEDULER", f"Starting scheduled tests: {', '.join(tests)}")
        self.broadcast({"type": "scheduler", "data": schedule})
        self._publish_status()
        self._run_task = asyncio.create_task(self._execute_run(scheduled_tests=tests, scheduled_settings=copy.deepcopy(schedule)))

    async def _scheduler_loop(self):
        while True:
            try:
                await self._check_schedule()
            except Exception as e:
                self.logger.info("SCHEDULER", f"Scheduler error: {type(e).__name__}: {e}")
            await asyncio.sleep(1)

    def update_config(self, section, key, data):
        if section == "generator":
            self.config["generator"].update(data)
        elif section == "categories" and key:
            if key in self.config["categories"]:
                self.config["categories"][key] = data
            else:
                raise ValueError(f"Unknown category: {key}")
        elif section == "clients":
            self.config["client_profiles"] = data
        elif section == "legitimate":
            self.config["legitimate_traffic"].update(data)
        else:
            raise ValueError(f"Unknown config section: {section}")

        self._save_config()

    def _save_config(self):
        dir_name = os.path.dirname(os.path.abspath(self.config_path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.config, f, indent=2)
                f.write("\n")
            os.replace(tmp_path, self.config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_docker_pool(self):
        if self._docker_pool is None:
            from ..docker_clients import DockerClientPool
            self._docker_pool = DockerClientPool(self.config, progress=lambda message: self.logger.info("DOCKER", message))
        return self._docker_pool

    async def cleanup(self):
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        await self.stop()
        await self._pool.cleanup()
        if self._docker_pool:
            await self._docker_pool.cleanup()
        self.logger.close()
        self._history_handler.close()
