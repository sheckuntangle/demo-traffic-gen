"""Round-based engine — orchestrates multi-client traffic generation with scheduling."""

import asyncio
import random
from enum import Enum

from .categories import get_all_categories
from .clients import ClientPool
from .config import get_enabled_categories


class RunMode(str, Enum):
    FULL = "full"
    TRIGGERS_ONLY = "triggers"
    LEGITIMATE_ONLY = "legit"


class Engine:
    def __init__(self, config, logger, stats, pool=None):
        self._config = config
        self._logger = logger
        self._stats = stats
        self._pool = pool or ClientPool(config)
        self._running = False
        self._stop_requested = False
        self._round_num = 0
        self._mode = None
        self._callbacks = {
            "on_round_start": [],
            "on_test_complete": [],
            "on_round_complete": [],
        }

    def on(self, event, callback):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _emit(self, event, **kwargs):
        for cb in self._callbacks.get(event, []):
            try:
                cb(**kwargs)
            except Exception:
                pass

    def request_stop(self):
        self._stop_requested = True

    @property
    def is_running(self):
        return self._running

    @property
    def round_num(self):
        return self._round_num

    @property
    def mode(self):
        return self._mode

    async def start(self, mode=RunMode.TRIGGERS_ONLY):
        self._running = True
        self._stop_requested = False
        self._round_num = 0
        self._mode = mode

        self._logger.info("SYSTEM", f"Starting engine in {mode.value} mode...")
        await self._pool.start()
        self._logger.info("SYSTEM", f"Browser launched with {len(self._pool.get_clients())} client(s)")

        try:
            if mode == RunMode.FULL:
                await self._run_full_mode()
            elif mode == RunMode.LEGITIMATE_ONLY:
                await self._run_legitimate_only()
            else:
                await self._run_triggers_only()
        finally:
            self._running = False

    async def _interruptible_sleep(self, seconds):
        try:
            remaining = seconds
            while remaining > 0 and not self._stop_requested:
                await asyncio.sleep(min(1, remaining))
                remaining -= 1
        except asyncio.CancelledError:
            pass

    # --- Full mode: concurrent legit + trigger loops ---

    async def _run_full_mode(self):
        await asyncio.gather(
            self._legitimate_loop(),
            self._trigger_loop(),
        )

    async def _legitimate_loop(self):
        interval = self._config["generator"].get("legitimate_interval_seconds", 45)
        while not self._stop_requested:
            self._logger.info("SYSTEM", "Running legitimate traffic round...")
            await self._execute_legitimate_round()
            self._logger.info("SYSTEM", f"Next legitimate traffic in {interval}s...")
            await self._interruptible_sleep(interval)

    async def _trigger_loop(self):
        interval = self._config["generator"]["round_interval_seconds"]
        max_rounds = self._config["generator"]["max_rounds"]

        self._logger.info("SYSTEM", f"First trigger round in {interval}s...")
        await self._interruptible_sleep(interval)

        while not self._stop_requested:
            self._round_num += 1
            if max_rounds > 0 and self._round_num > max_rounds:
                self._logger.info("SYSTEM", f"Reached max rounds ({max_rounds}), stopping triggers.")
                break

            await self._execute_trigger_round()
            await self._pool.recycle_if_needed()

            if max_rounds > 0 and self._round_num >= max_rounds:
                break

            self._logger.info("SYSTEM", f"Next trigger round in {interval}s...")
            await self._interruptible_sleep(interval)

    # --- Triggers-only mode (original behavior) ---

    async def _run_triggers_only(self):
        max_rounds = self._config["generator"]["max_rounds"]
        interval = self._config["generator"]["round_interval_seconds"]

        while not self._stop_requested:
            self._round_num += 1
            if max_rounds > 0 and self._round_num > max_rounds:
                self._logger.info("SYSTEM", f"Reached max rounds ({max_rounds}), stopping.")
                break

            await self._execute_combined_round()

            if self._stop_requested:
                break
            await self._pool.recycle_if_needed()
            if max_rounds > 0 and self._round_num >= max_rounds:
                break

            self._logger.info("SYSTEM", f"Next round in {interval}s...")
            await self._interruptible_sleep(interval)

    # --- Legitimate-only mode ---

    async def _run_legitimate_only(self):
        interval = self._config["generator"].get("legitimate_interval_seconds", 45)
        max_rounds = self._config["generator"]["max_rounds"]

        while not self._stop_requested:
            self._round_num += 1
            if max_rounds > 0 and self._round_num > max_rounds:
                break

            self._logger.info("SYSTEM", f"Running legitimate traffic round {self._round_num}...")
            await self._execute_legitimate_round()
            await self._pool.recycle_if_needed()

            if max_rounds > 0 and self._round_num >= max_rounds:
                break

            self._logger.info("SYSTEM", f"Next round in {interval}s...")
            await self._interruptible_sleep(interval)

    # --- Round execution ---

    async def _execute_combined_round(self):
        self._logger.info("SYSTEM", f"{'='*80}")
        self._logger.info("SYSTEM", f"Starting Round {self._round_num}")
        self._logger.info("SYSTEM", f"{'='*80}")
        self._emit("on_round_start", round_num=self._round_num)

        enabled = get_enabled_categories(self._config)
        all_categories = get_all_categories()

        categories_to_run = []
        for cat_name in enabled:
            cat_cls = all_categories.get(cat_name)
            if cat_cls:
                categories_to_run.append(cat_cls())

        legit_cls = all_categories.get("legitimate")
        if legit_cls:
            categories_to_run.append(legit_cls())

        random.shuffle(categories_to_run)
        await self._run_categories_on_clients(categories_to_run)

        round_summary = self._stats.finish_round()
        self._logger.info("SYSTEM",
                          f"Round {self._round_num} complete: "
                          f"{round_summary['total_pass']} passed, "
                          f"{round_summary['total_fail']} failed")
        self._emit("on_round_complete", round_num=self._round_num, summary=round_summary)

    async def _execute_trigger_round(self):
        self._logger.info("SYSTEM", f"{'='*80}")
        self._logger.info("SYSTEM", f"Starting Trigger Round {self._round_num}")
        self._logger.info("SYSTEM", f"{'='*80}")
        self._emit("on_round_start", round_num=self._round_num)

        enabled = get_enabled_categories(self._config)
        all_categories = get_all_categories()

        categories_to_run = []
        for cat_name in enabled:
            cat_cls = all_categories.get(cat_name)
            if cat_cls:
                categories_to_run.append(cat_cls())

        random.shuffle(categories_to_run)
        await self._run_categories_on_clients(categories_to_run)

        round_summary = self._stats.finish_round()
        self._logger.info("SYSTEM",
                          f"Trigger Round {self._round_num} complete: "
                          f"{round_summary['total_pass']} passed, "
                          f"{round_summary['total_fail']} failed")
        self._emit("on_round_complete", round_num=self._round_num, summary=round_summary)

    async def _execute_legitimate_round(self):
        all_categories = get_all_categories()
        legit_cls = all_categories.get("legitimate")
        if not legit_cls:
            return
        await self._run_categories_on_clients([legit_cls()])

    async def _run_categories_on_clients(self, categories):
        clients = self._pool.get_clients()
        tasks = [
            self._run_client_round(client, categories)
            for client in clients
        ]
        await asyncio.gather(*tasks)

    async def _run_client_round(self, client, categories):
        client_name = client.profile.name
        source_ip = client.profile.source_ip

        cats = list(categories)
        random.shuffle(cats)

        for category in cats:
            if self._stop_requested:
                break

            self._logger.info(category.display_name,
                              f"[{client_name}] Running {category.display_name} tests")

            try:
                results = await category.run(
                    client.browser_context,
                    self._config,
                    source_ip=source_ip,
                )
            except Exception as e:
                self._logger.log_result(
                    category.name, "ERROR", "category execution",
                    "FAIL", str(e)[:80], client_name=client_name,
                    round_num=self._round_num,
                )
                self._stats.record(category.name, False)
                continue

            for result in results:
                result.client_name = client_name
                status = "PASS" if result.success else "FAIL"
                self._logger.log_result(
                    category.name, result.test_type, result.target,
                    status, result.message, client_name=client_name,
                    round_num=self._round_num,
                )
                self._stats.record(category.name, result.success)
                self._emit("on_test_complete", result=result)

    # --- Single-category run (for "Run Now" from GUI) ---

    async def run_single_category(self, category_name):
        all_categories = get_all_categories()
        cat_cls = all_categories.get(category_name)
        if not cat_cls:
            raise ValueError(f"Unknown category: {category_name}")

        await self._pool.start()
        self._logger.info("SYSTEM", f"Running single category: {cat_cls.display_name}")
        await self._run_categories_on_clients([cat_cls()])
        self._logger.info("SYSTEM", f"Single category run complete: {cat_cls.display_name}")

    async def cleanup(self):
        await self._pool.cleanup()
