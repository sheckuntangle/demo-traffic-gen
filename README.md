# Firewall Demo Traffic Generator

Multi-client, long-running traffic generator for populating firewall reporting dashboards. Generates realistic traffic across 8 firewall service categories with a terminal UI for monitoring.

## Quick Start

```bash
# Install everything (Ubuntu — requires sudo)
./install.sh

# Launch with TUI
python3 -m demo_generator

# Or run headless (no TUI, console output only)
python3 -m demo_generator --headless
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

Each round interleaves blocked/alerted traffic with legitimate "allowed" traffic (~60/40 ratio by default) so the firewall dashboard shows a realistic mix.

## Multi-Client

The generator simulates multiple clients with different browser fingerprints (user agents, viewports, timezones). For actual source IP diversity in firewall reports, configure IP aliasing on the host:

```bash
# Add extra IPs to your interface
sudo ip addr add 10.0.1.101/24 dev eth0
sudo ip addr add 10.0.1.102/24 dev eth0
```

Then set `source_ip` in the `client_profiles` section of `config.json`.

## CLI Options

```
python3 -m demo_generator [OPTIONS]

  --config PATH       Config file path (default: config.json)
  --headless          Run without TUI (console-only output)
  --rounds N          Number of rounds, 0=unlimited (default: from config)
  --interval SECS     Seconds between rounds (default: from config)
  --clients N         Number of simulated clients (default: from config)
  --categories LIST   Comma-separated category names to enable
  --log-dir PATH      Log output directory (default: from config)
```

### Examples

```bash
# Run 5 rounds with 2 clients, 60-second intervals
python3 -m demo_generator --headless --rounds 5 --clients 2 --interval 60

# Run only DNS filter and geo-IP categories
python3 -m demo_generator --headless --categories dns_filter,geo_ip

# Run overnight (unlimited rounds, 5-minute intervals)
python3 -m demo_generator --rounds 0 --interval 300
```

## TUI Controls

| Key | Action |
|-----|--------|
| `s` | Start / Stop the generator |
| `c` | Clear the log panel |
| `q` | Quit (graceful shutdown) |

The TUI shows live logs, per-category statistics, and category toggles for enabling/disabling test types at runtime.

## Configuration

Edit `config.json` to customize:

- **generator**: Round interval, max rounds, client count, traffic ratio
- **client_profiles**: Browser fingerprints and optional source IPs
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
traffic_generator.py     # Legacy single-pass script (still works)
demo_generator/          # New multi-client package
├── __main__.py          # CLI entry point
├── config.py            # Config loading
├── engine.py            # Round scheduler and orchestrator
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
└── tui/                 # Textual terminal UI
    └── app.py
```

## Output

- Color-coded real-time console output (headless mode) or TUI display
- Timestamped log files in `logs/` directory (rotated at 10MB)
- Per-round and cumulative statistics summary
