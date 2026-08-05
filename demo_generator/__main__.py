"""CLI entry point for the traffic generator. Run with: python -m demo_generator"""

import argparse
import asyncio
import signal
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        prog="demo_generator",
        description="Firewall Demo Traffic Generator — generate realistic multi-client traffic for firewall reporting",
    )
    parser.add_argument("--config", default="config.json", help="Path to config file (default: config.json)")

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--web", action="store_true", default=True, help="Run with web GUI (default)")
    mode_group.add_argument("--headless", action="store_true", help="Run without GUI (console output only)")
    mode_group.add_argument("--tui", action="store_true", help="Run with terminal UI (legacy)")

    parser.add_argument("--host", default="0.0.0.0", help="Web GUI bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Web GUI port (default: 8080)")
    parser.add_argument("--rounds", type=int, default=None, help="Number of rounds (0=unlimited, default: from config)")
    parser.add_argument("--interval", type=int, default=None, help="Seconds between rounds (default: from config)")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category names to enable")
    parser.add_argument("--log-dir", default=None, help="Log output directory (default: from config)")
    return parser.parse_args()


def apply_overrides(config, args):
    if args.rounds is not None:
        config["generator"]["max_rounds"] = args.rounds
    if args.interval is not None:
        config["generator"]["round_interval_seconds"] = args.interval
    if args.categories is not None:
        enabled = [c.strip() for c in args.categories.split(",")]
        for cat_name, cat_config in config["categories"].items():
            cat_config["enabled"] = cat_name in enabled
    if args.log_dir is not None:
        config["generator"]["log_dir"] = args.log_dir


async def run_headless(config):
    from .engine import Engine, RunMode
    from .logger import Logger
    from .stats import Stats

    logger = Logger(log_dir=config["generator"].get("log_dir", "./logs"))
    stats = Stats()
    engine = Engine(config, logger, stats)

    loop = asyncio.get_event_loop()

    def handle_signal():
        logger.info("SYSTEM", "Shutdown signal received, finishing current test...")
        engine.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    try:
        await engine.start(mode=RunMode.TRIGGERS_ONLY)
    except KeyboardInterrupt:
        pass
    finally:
        await engine.cleanup()
        logger.print_summary(stats)
        logger.close()


def main():
    args = parse_args()

    from .config import load_config
    config = load_config(args.config)
    apply_overrides(config, args)

    if args.headless:
        asyncio.run(run_headless(config))
    elif args.tui:
        from .tui.app import TrafficGeneratorApp
        app = TrafficGeneratorApp(config)
        app.run()
    else:
        from .web.server import run_web
        run_web(config, args.config, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
