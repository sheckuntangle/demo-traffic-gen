# Firewall Demo Traffic Generator

Multi-client, long-running traffic generator for populating firewall reporting dashboards. Generates realistic traffic across 8 firewall service categories with a web-based GUI for control and monitoring.

## Quick Start

```bash
# Install everything (Ubuntu — one time, requires sudo)
./install.sh

# Launch web GUI (default — opens at http://localhost:8080)
./run.sh

# Or run headless (console output only, no GUI)
./run.sh --headless
```

## What It Does

Generates traffic that triggers and populates reporting for these firewall services:

| Category | What It Tests |
|----------|---------------|
| **App Control** | SSH connections (block), Facebook (reject), Gmail (alert) |
| **DNS Filter** | mlb.com (block), nfl.com (reject), nba.com (alert) |
| **Geo-IP** | France (block), Switzerland (reject), Sweden (alert) |
| **Web Filter** | Marijuana/weedmaps (block), Shopping/amazon (reject), Sports/espn (alert) |
| **Dynamic Blocklist** | Specific IPs and domains (208.67.222.222, ebay, wikipedia) |
| **Security** | Blocked IPs (9.9.9.9) |
| **IP Reputation** | BrightCloud-flagged malicious IPs |
| **URL Reputation** | BrightCloud-flagged high-risk URLs |
| **Legitimate Traffic** | High-volume normal browsing, DNS, and pings for realistic reporting |

Each round interleaves blocked/alerted traffic with legitimate "allowed" traffic so the firewall dashboard shows a realistic mix.

## Multi-Client

The generator simulates multiple clients with different browser fingerprints (user agents, viewports, timezones). For actual source IP diversity in firewall reports, use the **IP Aliasing** section in the web GUI's Configuration tab to add extra IPs to your network interface, then assign them to client profiles.

## CLI Options

```
./run.sh [OPTIONS]

  --web               Run with web GUI (default, http://localhost:8080)
  --headless          Run without GUI (console-only output)
  --tui               Run with terminal UI (legacy)
  --host ADDR         Web GUI bind address (default: 0.0.0.0)
  --port PORT         Web GUI port (default: 8080)
  --config PATH       Config file path (default: config.json)
  --rounds N          Number of rounds, 0=unlimited (default: from config)
  --interval SECS     Seconds between rounds (default: from config)
  --clients N         Number of simulated clients (default: from config)
  --categories LIST   Comma-separated category names to enable
  --log-dir PATH      Log output directory (default: from config)
```

### Examples

```bash
# Launch web GUI on custom port
./run.sh --port 9090

# Run headless with 5 rounds
./run.sh --headless --rounds 5 --clients 2 --interval 60

# Run only DNS filter and geo-IP categories
./run.sh --headless --categories dns_filter,geo_ip
```

## Web GUI

The web interface at `http://localhost:8080` provides:

- **Dashboard**: Start/Stop controls with three run modes (Full Run, Triggers Only, Legitimate Only), per-category stats cards with "Run Now" buttons, and a live log stream
- **Configuration**: IP aliasing, client profiles, generator settings, per-category targets (add/remove IPs, URLs, domains), and legitimate traffic pools — all saved to config.json
- **Run Modes**:
  - **Full Run**: Continuous legitimate traffic with periodic trigger rounds — ideal for overnight demos
  - **Triggers Only**: All enabled categories + legitimate traffic per round
  - **Legitimate Only**: Clean passing traffic only

## Configuration

Edit via the web GUI Configuration tab, or directly in `config.json`:

- **generator**: Round interval, legitimate interval, max rounds, client count, sample sizes
- **client_profiles**: Browser fingerprints and source IPs for multi-client simulation
- **categories**: Targets for each firewall service (enable/disable individually)
- **legitimate_traffic**: Pool of allowed domains, URLs, and ping targets

## IP & URL Reputation

The `ip_reputation` and `url_reputation` categories need IPs/URLs that your BrightCloud service classifies as malicious/high-risk. The config ships with placeholder values — update them by:

1. Check candidates at [BrightCloud Lookup](https://www.brightcloud.com/tools/url-ip-lookup.php)
2. Pull from public threat feeds: [abuse.ch Feodo Tracker](https://feodotracker.abuse.ch/), [Spamhaus DROP](https://www.spamhaus.org/drop/), [URLhaus](https://urlhaus.abuse.ch/)
3. Test against your firewall to confirm they trigger the expected blocks

These targets change over time — refresh periodically.

## Files

```
config.json              # All targets and settings
requirements.txt         # Python dependencies
install.sh               # One-time Ubuntu setup (deps, venv, sudoers)
run.sh                   # Launch wrapper (uses venv automatically)
traffic_generator.py     # Legacy single-pass script (still works)
demo_generator/          # Multi-client package
├── __main__.py          # CLI entry point (--web default)
├── config.py            # Config loading and defaults
├── engine.py            # Round scheduler with run modes
├── clients.py           # Multi-client browser context pool
├── logger.py            # Dual console + file logging
├── stats.py             # Statistics tracking
├── primitives.py        # Async test functions (ping, DNS, web, SSH, TCP)
├── categories/          # Test category modules
│   ├── legitimate.py    # Allowed traffic generation
│   ├── app_control.py   # SSH, Facebook, Gmail
│   ├── dns_filter.py    # Domain blocking
│   ├── geo_ip.py        # Country-based IP blocking
│   ├── web_filter.py    # URL category filtering
│   ├── dynamic_blocklist.py
│   ├── security.py
│   ├── ip_reputation.py
│   └── url_reputation.py
├── web/                 # FastAPI web GUI (default)
│   ├── server.py        # FastAPI app + uvicorn
│   ├── run_manager.py   # Engine lifecycle manager
│   ├── routes_api.py    # REST API + IP aliasing endpoints
│   ├── routes_ws.py     # WebSocket log streaming
│   └── static/          # Frontend assets
└── tui/                 # Textual terminal UI (legacy)
    └── app.py
```

## Output

- Live log stream in the web GUI dashboard (via WebSocket)
- Color-coded console output in headless mode
- Timestamped log files in `logs/` directory (rotated at 10MB)
- Per-round and cumulative statistics
