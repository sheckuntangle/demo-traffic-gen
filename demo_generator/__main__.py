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
    parser.add_argument("--headless", action="store_true", help="Run without TUI (console output only)")
    parser.add_argument("--rounds", type=int, default=None, help="Number of rounds (0=unlimited, default: from config)")
    parser.add_argument("--interval", type=int, default=None, help="Seconds between rounds (default: from config)")
    parser.add_argument("--clients", type=int, default=None, help="Number of simulated clients (default: from config)")
    parser.add_argument("--categories", type=str, default=None, help="Comma-separated category names to enable")
    parser.add_argument("--log-dir", default=None, help="Log output directory (default: from config)")
    return parser.parse_args()


async def run_headless(config, overrides):
    from .engine import Engine
    from .logger import Logger
    from .stats import Stats

    logger = Logger(log_dir=config["generator"].get("log_dir", "./logs"))
    stats = Stats()
    engine = Engine(config, logger, stats)

    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def handle_signal():
        logger.info("SYSTEM", "Shutdown signal received, finishing current test...")
        engine.request_stop()
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    try:
        await engine.start()
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

    overrides = {}
    if args.rounds is not None:
        config["generator"]["max_rounds"] = args.rounds
    if args.interval is not None:
        config["generator"]["round_interval_seconds"] = args.interval
    if args.clients is not None:
        config["generator"]["client_count"] = args.clients
    if args.categories is not None:
        enabled = [c.strip() for c in args.categories.split(",")]
        for cat_name, cat_config in config["categories"].items():
            cat_config["enabled"] = cat_name in enabled
    if args.log_dir is not None:
        config["generator"]["log_dir"] = args.log_dir

    if args.headless:
        asyncio.run(run_headless(config, overrides))
    else:
        from .tui.app import TrafficGeneratorApp

        app = TrafficGeneratorApp(config)
        app.run()


if __name__ == "__main__":
    main()
