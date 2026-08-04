# Firewall Demo Traffic Generator

## Purpose
Multi-client, long-running traffic generator for populating firewall reporting dashboards. Generates realistic traffic across 8 firewall service categories with legitimate traffic interleaving.

## Architecture

Two implementations exist:
- `traffic_generator.py` — Legacy single-pass script (still functional)
- `demo_generator/` — New async multi-client package with TUI

### Package Structure
```
demo_generator/
├── __main__.py        — CLI entry point (argparse, mode dispatch)
├── config.py          — Config loading and validation
├── engine.py          — Round scheduler, multi-client orchestrator
├── clients.py         — Playwright browser context pool with varied fingerprints
├── logger.py          — Dual console + file logging with TUI event callbacks
├── stats.py           — Thread-safe per-category statistics
├── primitives.py      — Async test functions (ping, dns, web, ssh, tcp)
├── categories/        — One module per firewall service category
│   ├── __init__.py    — Base class with auto-registration
│   ├── legitimate.py  — High-volume allowed traffic
│   ├── app_control.py — SSH, Facebook, Gmail
│   ├── dns_filter.py  — mlb/nfl/nba domains
│   ├── geo_ip.py      — France/Switzerland/Sweden IPs
│   ├── web_filter.py  — marijuana/shopping/sports URLs
│   ├── dynamic_blocklist.py
│   ├── security.py
│   ├── ip_reputation.py
│   └── url_reputation.py
└── tui/
    └── app.py         — Textual terminal UI
```

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
| Legitimate | 60+ DNS domains, 48+ web URLs, pings | allowed (for reporting volume) |

## Key Design Decisions
- Async throughout: `playwright.async_api` + `asyncio` for concurrent multi-client execution
- Categories auto-register via `__init_subclass__` — adding a new category is one file
- Legitimate traffic interleaved with trigger traffic (configurable 60/40 ratio)
- Browser contexts recycled every ~10 rounds to prevent memory leaks during overnight runs
- Source IP binding supported via IP aliasing for real multi-IP reporting

## Requirements
- Python 3.8+
- playwright, paramiko, textual (see requirements.txt)

## Usage
```bash
python3 -m demo_generator                              # TUI mode
python3 -m demo_generator --headless                   # Console-only
python3 -m demo_generator --headless --rounds 1        # Single round
python3 -m demo_generator --categories dns_filter,geo_ip --clients 2
```
