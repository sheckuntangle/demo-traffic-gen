"""Round-based engine — orchestrates multi-client traffic generation with scheduling."""

import asyncio
import random

from .categories import get_all_categories
from .clients import ClientPool
from .config import get_enabled_categories


class Engine:
    def __init__(self, config, logger, stats):
        self._config = config
        self._logger = logger
        self._stats = stats
        self._pool = ClientPool(config)
        self._running = False
        self._stop_requested = False
        self._round_num = 0
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

    async def start(self):
        self._running = True
        self._stop_requested = False
        max_rounds = self._config["generator"]["max_rounds"]
        interval = self._config["generator"]["round_interval_seconds"]

        self._logger.info("SYSTEM", "Starting traffic generator engine...")
        await self._pool.start()
        self._logger.info("SYSTEM", f"Browser launched with {len(self._pool.get_clients())} client(s)")

        try:
            while not self._stop_requested:
                self._round_num += 1

                if max_rounds > 0 and self._round_num > max_rounds:
                    self._logger.info("SYSTEM", f"Reached max rounds ({max_rounds}), stopping.")
                    break

                await self._execute_round()

                if self._stop_requested:
                    break

                await self._pool.recycle_if_needed()

                if max_rounds > 0 and self._round_num >= max_rounds:
                    break

                self._logger.info("SYSTEM", f"Next round in {interval} seconds...")
                try:
                    await asyncio.wait_for(self._wait_for_stop(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

        finally:
            self._running = False

    async def _wait_for_stop(self):
        while not self._stop_requested:
            await asyncio.sleep(1)

    async def _execute_round(self):
        self._logger.info("SYSTEM", f"{'='*80}")
        self._logger.info("SYSTEM", f"Starting Round {self._round_num}")
        self._logger.info("SYSTEM", f"{'='*80}")
        self._emit("on_round_start", round_num=self._round_num)

        enabled = get_enabled_categories(self._config)
        all_categories = get_all_categories()

        categories_to_run = []
        for cat_name, cat_config in enabled.items():
            cat_cls = all_categories.get(cat_name)
            if cat_cls:
                categories_to_run.append(cat_cls())

        legit_cls = all_categories.get("legitimate")
        if legit_cls:
            categories_to_run.append(legit_cls())

        random.shuffle(categories_to_run)

        clients = self._pool.get_clients()
        tasks = [
            self._run_client_round(client, categories_to_run)
            for client in clients
        ]
        await asyncio.gather(*tasks)

        round_summary = self._stats.finish_round()
        self._logger.info("SYSTEM",
                          f"Round {self._round_num} complete: "
                          f"{round_summary['total_pass']} passed, "
                          f"{round_summary['total_fail']} failed")
        self._emit("on_round_complete", round_num=self._round_num, summary=round_summary)

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

    async def cleanup(self):
        await self._pool.cleanup()
