# Firewall Demo Traffic Generator

## Purpose
Multi-client, long-running traffic generator for populating firewall reporting dashboards. Generates realistic traffic across 8 firewall service categories with a web-based GUI for control, configuration, and monitoring.

## Architecture

- `traffic_generator.py` — Legacy single-pass script (still functional)
- `demo_generator/` — Async multi-client package with web GUI

### Package Structure
```
demo_generator/
├── __main__.py        — CLI entry point (--web default, --headless, --tui)
├── config.py          — Config loading, validation, defaults
├── engine.py          — Round scheduler with RunMode (full/triggers/legit)
├── clients.py         — Playwright browser context pool with varied fingerprints
├── logger.py          — Dual console + file logging with quiet mode for web
├── stats.py           — Thread-safe per-category statistics
├── primitives.py      — Async test functions (ping, dns, web, ssh, tcp)
├── categories/        — One module per firewall service category
│   ├── __init__.py    — Base class with auto-registration
│   ├── legitimate.py  — High-volume allowed traffic (configurable sample sizes)
│   ├── app_control.py — SSH, Facebook, Gmail
│   ├── dns_filter.py  — mlb/nfl/nba domains
│   ├── geo_ip.py      — France/Switzerland/Sweden IPs
│   ├── web_filter.py  — marijuana/shopping/sports URLs
│   ├── dynamic_blocklist.py
│   ├── security.py
│   ├── ip_reputation.py
│   └── url_reputation.py
├── web/               — FastAPI web GUI (default interface)
│   ├── server.py      — FastAPI app + uvicorn launcher
│   ├── run_manager.py — Engine lifecycle, config persistence, WS broadcast
│   ├── routes_api.py  — REST endpoints (control, config, stats, IP aliasing)
│   ├── routes_ws.py   — WebSocket for live log streaming
│   └── static/        — Frontend (Bootstrap 5, vanilla JS, no build step)
│       ├── index.html
│       ├── app.js
│       └── style.css
└── tui/               — Textual terminal UI (legacy, --tui flag)
    └── app.py
```

## Run Modes
- **Full Run** — Continuous legitimate traffic + periodic trigger rounds (overnight mode)
- **Triggers Only** — All enabled categories + legitimate per round
- **Legitimate Only** — Clean passing traffic only
- **Single Category** — "Run Now" button per category from the web GUI

## Firewall Service Categories

| Category | Targets | Actions |
|----------|---------|---------|
| App Control | SSH (github.com:22), Facebook, Gmail | block, reject, alert |
| DNS Filter | mlb.com, nfl.com, nba.com | block, reject, alert |
| Geo-IP | France, Switzerland, Sweden IPs | block, reject, alert |
| Web Filter | weedmaps, amazon, espn | block, reject, alert |
| Dynamic Blocklist | 208.67.222.222, ebay, wikipedia | block |
| Security | 9.9.9.9 | block |
| IP Reputation | BrightCloud-flagged IPs | block |
| URL Reputation | BrightCloud-flagged URLs | block |
| Legitimate | 60+ DNS domains, 48+ web URLs, pings | allowed (reporting volume) |

## Key Design Decisions
- Web GUI default (FastAPI + WebSocket), headless CLI and TUI as alternatives
- Async throughout: `playwright.async_api` + `asyncio` for concurrent multi-client execution
- Full Run mode: two concurrent loops (legit every 45s, triggers every 300s)
- Categories auto-register via `__init_subclass__` — adding a new category is one file
- Legitimate traffic sample sizes configurable via `dns/web/ping_sample_range` in config
- IP aliasing managed from the web GUI (sudoers rule set up by install.sh)
- Config changes saved to config.json atomically via temp file + os.replace()
- Browser contexts recycled every ~10 rounds to prevent memory leaks overnight

## Requirements
- Ubuntu (install.sh handles all setup)
- Python 3.8+
- playwright, paramiko, fastapi, uvicorn, textual (see requirements.txt)

## Usage
```bash
./install.sh                                    # One-time setup
./run.sh                                        # Web GUI at http://localhost:8080
./run.sh --headless                             # Console-only
./run.sh --headless --rounds 1                  # Single round
./run.sh --port 9090                            # Custom port
./run.sh --headless --categories dns_filter,geo_ip --clients 2
```
