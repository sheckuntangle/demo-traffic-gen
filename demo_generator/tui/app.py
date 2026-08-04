"""Textual TUI application for the traffic generator."""

import asyncio
from datetime import datetime, timedelta

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Label,
    RichLog,
    Static,
)

from ..categories import get_all_categories
from ..config import get_enabled_categories
from ..engine import Engine
from ..logger import Logger
from ..stats import Stats


class StatusBar(Static):
    status = reactive("Stopped")
    round_num = reactive(0)
    max_rounds = reactive(0)
    elapsed = reactive("00:00:00")
    next_round = reactive("")

    def render(self):
        round_display = f"Round {self.round_num}"
        if self.max_rounds > 0:
            round_display += f" / {self.max_rounds}"
        else:
            round_display += " / unlimited"

        next_info = f"  |  Next: {self.next_round}" if self.next_round else ""
        return f"  [{self.status}]  |  {round_display}  |  Elapsed: {self.elapsed}{next_info}"


class StatsTable(Static):
    def compose(self) -> ComposeResult:
        yield DataTable(id="stats-table")

    def on_mount(self):
        table = self.query_one("#stats-table", DataTable)
        table.add_columns("Category", "Pass", "Fail", "Total")
        table.zebra_stripes = True

    def update_stats(self, cumulative):
        table = self.query_one("#stats-table", DataTable)
        table.clear()
        for cat_name, cat_stats in cumulative.get("categories", {}).items():
            p = cat_stats["pass"]
            f = cat_stats["fail"]
            table.add_row(cat_name, str(p), str(f), str(p + f))

        total_p = cumulative.get("total_pass", 0)
        total_f = cumulative.get("total_fail", 0)
        table.add_row("TOTAL", str(total_p), str(total_f), str(total_p + total_f))


class CategoryToggles(Static):
    def __init__(self, config):
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        yield Label("Categories", classes="section-header")
        all_cats = get_all_categories()
        for cat_name, cat_cls in all_cats.items():
            if cat_name == "legitimate":
                continue
            enabled = self._config["categories"].get(cat_name, {}).get("enabled", False)
            yield Checkbox(cat_cls.display_name, value=enabled, id=f"cat-{cat_name}")

    def on_checkbox_changed(self, event: Checkbox.Changed):
        checkbox_id = event.checkbox.id
        if checkbox_id and checkbox_id.startswith("cat-"):
            cat_name = checkbox_id[4:]
            if cat_name in self._config["categories"]:
                self._config["categories"][cat_name]["enabled"] = event.value


class TrafficGeneratorApp(App):
    CSS = """
    Screen {
        layout: grid;
        grid-size: 3 3;
        grid-columns: 1fr 3fr 1fr;
        grid-rows: auto 1fr auto;
    }

    #status-bar {
        column-span: 3;
        height: 3;
        background: $primary-darken-2;
        color: $text;
        content-align: center middle;
        text-style: bold;
        padding: 0 2;
    }

    #left-panel {
        row-span: 1;
        padding: 1;
        border: solid $primary;
    }

    #log-panel {
        row-span: 1;
        padding: 1;
        border: solid $primary;
    }

    #right-panel {
        row-span: 1;
        padding: 1;
        border: solid $primary;
    }

    #controls {
        column-span: 3;
        height: auto;
        padding: 1;
        layout: horizontal;
    }

    #controls Button {
        margin: 0 2;
    }

    .section-header {
        text-style: bold;
        padding: 0 0 1 0;
        color: $accent;
    }

    #stats-table {
        height: 100%;
    }

    #log {
        height: 100%;
    }
    """

    BINDINGS = [
        Binding("s", "toggle_running", "Start/Stop"),
        Binding("q", "quit", "Quit"),
        Binding("c", "clear_log", "Clear Log"),
    ]

    TITLE = "Firewall Demo Traffic Generator"

    def __init__(self, config):
        super().__init__()
        self._config = config
        self._traffic_logger = None
        self._stats = None
        self._engine = None
        self._engine_task = None
        self._run_start_time = None
        self._timer_task = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(id="status-bar")
        yield Vertical(
            CategoryToggles(self._config),
            id="left-panel",
        )
        yield Vertical(
            Label("Live Log", classes="section-header"),
            RichLog(id="log", highlight=True, markup=True),
            id="log-panel",
        )
        yield Vertical(
            Label("Statistics", classes="section-header"),
            StatsTable(id="stats-widget"),
            id="right-panel",
        )
        yield Horizontal(
            Button("Start", id="start-btn", variant="success"),
            Button("Stop", id="stop-btn", variant="error", disabled=True),
            Label(id="log-file-label"),
            id="controls",
        )
        yield Footer()

    def on_mount(self):
        self._stats = Stats()
        self._traffic_logger = Logger(log_dir=self._config["generator"].get("log_dir", "./logs"))
        self._traffic_logger.subscribe(self._on_log_entry)
        self._engine = Engine(self._config, self._traffic_logger, self._stats)
        self._engine.on("on_round_start", self._on_round_start)
        self._engine.on("on_round_complete", self._on_round_complete)

        log_label = self.query_one("#log-file-label", Label)
        log_label.update(f"Log: {self._traffic_logger.log_filename}")

    def _on_log_entry(self, entry):
        try:
            log_widget = self.query_one("#log", RichLog)
            status = entry.get("status", "")
            color = "green" if status == "PASS" else "red" if status == "FAIL" else "yellow" if status == "INFO" else "white"
            client = f"[cyan]\\[{entry.get('client_name', '')}][/] " if entry.get("client_name") else ""
            category = entry.get("category", "")
            target = entry.get("target", "")
            message = entry.get("message", "")
            line = f"{client}[blue]{category:18}[/] | {target:50} | [{color}]{status:4}[/] {message}"
            self.call_from_thread(log_widget.write, line)
        except Exception:
            pass

    def _on_round_start(self, round_num):
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            self.call_from_thread(setattr, status_bar, "round_num", round_num)
        except Exception:
            pass

    def _on_round_complete(self, round_num, summary):
        try:
            stats_widget = self.query_one("#stats-widget", StatsTable)
            cumulative = self._stats.get_cumulative()
            self.call_from_thread(stats_widget.update_stats, cumulative)
        except Exception:
            pass

    async def _run_engine(self):
        try:
            await self._engine.start()
        except Exception as e:
            log_widget = self.query_one("#log", RichLog)
            log_widget.write(f"[red]Engine error: {e}[/]")
        finally:
            self._set_stopped_state()

    def _set_stopped_state(self):
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.status = "Stopped"
            start_btn = self.query_one("#start-btn", Button)
            stop_btn = self.query_one("#stop-btn", Button)
            start_btn.disabled = False
            stop_btn.disabled = True
        except Exception:
            pass

    async def _update_elapsed(self):
        while self._run_start_time:
            try:
                elapsed = datetime.now() - self._run_start_time
                elapsed_str = str(timedelta(seconds=int(elapsed.total_seconds())))
                status_bar = self.query_one("#status-bar", StatusBar)
                status_bar.elapsed = elapsed_str
            except Exception:
                pass
            await asyncio.sleep(1)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "start-btn":
            self.action_toggle_running()
        elif event.button.id == "stop-btn":
            self.action_toggle_running()

    def action_toggle_running(self):
        if self._engine and self._engine.is_running:
            self._engine.request_stop()
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.status = "Stopping..."
        else:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.status = "Running"
            status_bar.max_rounds = self._config["generator"]["max_rounds"]

            start_btn = self.query_one("#start-btn", Button)
            stop_btn = self.query_one("#stop-btn", Button)
            start_btn.disabled = True
            stop_btn.disabled = False

            self._run_start_time = datetime.now()
            self._engine_task = asyncio.ensure_future(self._run_engine())
            self._timer_task = asyncio.ensure_future(self._update_elapsed())

    def action_clear_log(self):
        log_widget = self.query_one("#log", RichLog)
        log_widget.clear()

    async def action_quit(self):
        if self._engine and self._engine.is_running:
            self._engine.request_stop()
            if self._engine_task:
                await asyncio.wait_for(self._engine_task, timeout=10)
        if self._engine:
            await self._engine.cleanup()
        if self._traffic_logger:
            self._traffic_logger.print_summary(self._stats)
            self._traffic_logger.close()
        self._run_start_time = None
        self.exit()
