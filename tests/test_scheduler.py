from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from demo_generator.config import load_config
from demo_generator.web.run_manager import RunConflict, RunManager


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = self.directory.name + "/config.json"
        self.config = {"generator": {"log_dir": self.directory.name}, "client_profiles": []}
        self.manager = RunManager(self.config, self.path)
        self.when = datetime.now(timezone.utc) + timedelta(hours=1)

    async def asyncTearDown(self):
        await self.manager.cleanup()
        self.directory.cleanup()

    def schedule(self):
        return {"enabled": True, "scheduled_at": self.when.isoformat(),
                "tests": {"app_control": True, "dns_filter": False, "legitimate": True}}

    async def test_offsets_normalize_to_same_instant_and_survive_restart(self):
        data = self.schedule()
        data["scheduled_at"] = self.when.astimezone(timezone(timedelta(hours=-5))).isoformat()
        saved = self.manager.update_scheduler(data)
        self.assertEqual(datetime.fromisoformat(saved["scheduled_at"]), self.when)
        self.assertTrue(saved["scheduled_at"].endswith("+00:00"))
        self.assertEqual(load_config(self.path)["scheduler"], saved)
        await self.manager.cleanup()
        self.manager = RunManager(load_config(self.path), self.path)
        self.assertTrue(self.manager.config["scheduler"]["enabled"])

    async def test_due_schedule_runs_selected_tests_once_and_blocks_manual_runs(self):
        self.manager.update_scheduler(self.schedule())
        engine = SimpleNamespace(on=lambda *args: None, run_single_category=AsyncMock(), round_num=0)
        with patch.object(self.manager, "_get_active_pool", new=AsyncMock()), \
             patch("demo_generator.web.run_manager.Engine", return_value=engine):
            await self.manager._check_schedule(self.when - timedelta(seconds=1))
            self.assertIsNone(self.manager._run_task)
            await self.manager._check_schedule(self.when)
            with self.assertRaises(RunConflict):
                await self.manager.run_single("security")
            await self.manager._run_task
            self.assertEqual([call.args[0] for call in engine.run_single_category.call_args_list], ["app_control", "legitimate"])
            self.assertFalse(load_config(self.path)["scheduler"]["enabled"])
            await self.manager._check_schedule(self.when + timedelta(days=1))
            self.assertEqual(engine.run_single_category.await_count, 2)
            self.assertEqual(self.manager.get_status()["phase"], "idle")

    async def test_busy_runner_defers_schedule_without_consuming_it(self):
        self.manager.update_scheduler(self.schedule())
        self.manager._phase = "running"
        await self.manager._check_schedule(self.when)
        self.assertTrue(self.manager.config["scheduler"]["enabled"])
        self.assertIsNone(self.manager._run_task)
        self.manager._phase = "idle"

    async def test_disabled_schedule_never_dispatches(self):
        self.manager.update_scheduler({**self.schedule(), "enabled": False})
        await self.manager._check_schedule(self.when)
        self.assertIsNone(self.manager._run_task)

    async def test_reject_invalid_dates_and_test_selections(self):
        for changes in ({"scheduled_at": "2030-01-01T15:00"}, {"scheduled_at": "nonsense"},
                        {"scheduled_at": None}, {"tests": {}}, {"tests": {"unknown": True}},
                        {"tests": {"app_control": "yes"}}, {"enabled": "yes"},
                        {"scheduled_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.manager.update_scheduler({**self.schedule(), **changes})
        self.assertFalse(self.manager.config["scheduler"]["enabled"])

    async def test_persistence_failure_does_not_dispatch_or_lose_schedule(self):
        self.manager.update_scheduler(self.schedule())
        with patch.object(self.manager, "_save_config", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.manager._check_schedule(self.when)
        self.assertTrue(self.manager.config["scheduler"]["enabled"])
        self.assertIsNone(self.manager._run_task)


class BrowserTimezoneTests(unittest.TestCase):
    def test_eastern_and_romanian_browsers_display_and_save_same_instant(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const elements = {
    'scheduler-enabled': {checked: true},
    'scheduler-time': {value: process.env.LOCAL_TIME},
};
let saved;
const context = vm.createContext({
    document: {addEventListener() {}, getElementById: id => elements[id],
        querySelectorAll: () => [{dataset: {scheduleTest: 'app_control'}, checked: true}]},
    fetch: async (url, options) => { saved = JSON.parse(options.body); return {ok: true, json: async () => saved}; },
});
vm.runInContext(fs.readFileSync('demo_generator/web/static/app.js', 'utf8') + '\n globalThis.app = App;', context);
const app = context.app;
assert.equal(app.localDateTime('2030-11-10T20:00:00Z'), process.env.LOCAL_TIME);
app.receiveScheduler = () => {};
app.showToast = () => {};
(async () => {
    await app.saveScheduler();
    assert.equal(saved.scheduled_at, '2030-11-10T20:00:00.000Z');
    assert.equal(saved.tests.app_control, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        root = Path(__file__).resolve().parents[1]
        for zone, local in (("America/New_York", "2030-11-10T15:00"), ("Europe/Bucharest", "2030-11-10T22:00")):
            with self.subTest(zone=zone):
                subprocess.run(["node", "-e", script], cwd=root,
                               env={**os.environ, "TZ": zone, "LOCAL_TIME": local}, check=True, capture_output=True)
