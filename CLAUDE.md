# Firewall Demo Traffic Generator

## Project Purpose

Generates realistic multi-client network traffic behind a firewall to populate reporting dashboards. Designed for demo environments where a single Ubuntu server sits behind an NGFW/UTM appliance.

## Deployment

Two ways to run the controller:

**Docker Compose (recommended)** — self-contained, no host dependencies beyond Docker:
```bash
docker compose up --build -d          # Build and launch
# http://<docker-host>:8080           # Web GUI
docker compose logs -f controller     # Follow logs
docker compose down                   # Stop
```
The controller runs with host networking (for interface discovery). Runtime state (config, logs) persists in `./data/`, created on first startup from `config.example.json`. Docker socket is mounted for building worker images and managing macvlan networks.

**Legacy native install** — runs directly on the Ubuntu host:
```bash
./install.sh              # One-time setup (system deps, venv, Docker, Playwright)
./run.sh                  # Web GUI at http://localhost:8080
./run.sh --headless       # Console-only mode
```

## Topology

```
                ┌─────────────────┐
                │    Firewall      │
                │  (NGFW / UTM)    │
                └────────┬────────┘
                         │
                DHCP subnet (e.g. 10.0.1.0/24)
                         │
                ┌────────┴────────┐
                │  Ubuntu Server   │
                │  (traffic gen)   │
                │                  │
                │  Local mode:     │
                │    single IP     │
                │                  │
                │  Docker mode:    │
                │    container-1   │  10.0.1.101
                │    container-2   │  10.0.1.102
                │    container-3   │  10.0.1.103
                └─────────────────┘
```

## Architecture

- `compose.yaml` + `Dockerfile.controller` -- Docker Compose deployment (controller with host networking)
- `Dockerfile` -- Worker image for dynamically spawned Docker traffic clients
- `traffic_generator.py` -- Legacy single-pass script (still functional)
- `demo_generator/` -- Async multi-client package with web GUI

### Package Structure
```
demo_generator/
├── __main__.py        -- CLI entry point (--web default, --headless, --tui)
├── config.py          -- Config loading, defaults
├── engine.py          -- Round scheduler with RunMode (full/triggers/legit)
├── clients.py         -- Playwright browser context pool with varied fingerprints
├── docker_clients.py  -- Docker containers on macvlan for source IP diversity
├── logger.py          -- Dual console + file logging with quiet mode for web
├── stats.py           -- Thread-safe per-category statistics
├── primitives.py      -- Async test functions (ping, dns_query, web_request, http_to_ip, ssh_connect, tcp_connect)
├── categories/        -- One module per firewall service category
│   ├── __init__.py    -- Base class with auto-registration via __init_subclass__
│   ├── legitimate.py  -- High-volume allowed traffic (configurable sample sizes)
│   ├── app_control.py -- SSH, Facebook, Gmail
│   ├── dns_filter.py  -- mlb/nfl/nba domains
│   ├── geo_ip.py      -- France/Switzerland/Sweden IPs
│   ├── web_filter.py  -- marijuana/shopping/sports URLs
│   ├── dynamic_blocklist.py
│   ├── security.py
│   ├── idps.py        -- IDS/IPS signature testing via shell scripts
│   ├── ip_reputation.py
│   └── url_reputation.py
├── web/               -- FastAPI web GUI (default interface)
│   ├── server.py      -- FastAPI app + uvicorn launcher
│   ├── run_manager.py -- Engine lifecycle, config persistence, WS broadcast
│   ├── routes_api.py  -- REST endpoints (control, config, stats, IP aliasing, Docker)
│   ├── routes_ws.py   -- WebSocket for live log + status streaming
│   └── static/        -- Frontend (Bootstrap 5 dark theme, vanilla JS, no build step)
│       ├── index.html
│       ├── app.js
│       └── style.css
├── worker/            -- Runs inside Docker containers
│   └── service.py     -- FastAPI app, executes categories remotely via /run endpoint
└── tui/               -- Textual terminal UI (legacy, --tui flag)
    └── app.py
```

## Run Modes

- **Full Run** -- Continuous legitimate traffic + periodic trigger rounds (default intervals: legit every 45s, triggers every 300s, configurable)
- **Triggers Only** -- All enabled categories + legitimate per round
- **Legitimate Only** -- Clean passing traffic only
- **Single Category** -- "Run Now" button per category from the web GUI

## Firewall Service Categories

| Category | Targets | Actions |
|----------|---------|---------|
| App Control | SSH (github.com:22), Facebook, Gmail | block, reject, alert |
| DNS Filter | mlb.com, nfl.com, nba.com | block, reject, alert |
| Geo-IP | France, Switzerland, Sweden IPs | block, reject, alert |
| Web Filter | weedmaps, amazon, espn | block, reject, alert |
| Dynamic Blocklist | 208.67.222.222, ebay, wikipedia | block |
| Security | 9.9.9.9 | block |
| IDPS | IDS/IPS signature tests via curl scripts | block |
| IP Reputation | BrightCloud-flagged IPs | block |
| URL Reputation | BrightCloud-flagged URLs | block |
| Legitimate | 60+ DNS domains, 115+ web URLs, ping targets | allowed (reporting volume) |

## Key Patterns

**Adding a category**: Create a new file in `categories/`, subclass `TestCategory`, set `name` and `display_name` class attrs, implement `async def run()`. Registration is automatic via `__init_subclass__`. Add import to `categories/__init__.py`.

**Client dispatch**: Engine calls `client.run_category(category, config)`. For local clients (`ClientContext`), this calls `category.run()` directly. For Docker clients (`DockerClient`), this POSTs to the container's worker API. The engine doesn't know which type it's using.

**Docker dual-network**: Containers attach to both a macvlan network (test traffic, real IPs) and a bridge network (management API). The host can't reach macvlan IPs directly due to L2 isolation.

## Key Design Decisions

- Web GUI default (FastAPI + WebSocket), headless CLI and TUI as alternatives
- Async throughout: `playwright.async_api` + `asyncio` for concurrent multi-client execution
- Categories auto-register via `__init_subclass__`
- Legitimate traffic sample sizes configurable via `dns/web/ping_sample_range` in config
- IP aliasing managed from the web GUI (sudoers rule set up by install.sh)
- Config changes saved to config.json atomically via temp file + os.replace()
- Browser contexts recycled every ~10 rounds to prevent memory leaks overnight

## Commands

```bash
# Docker Compose (recommended)
docker compose up --build -d                    # Build and launch controller
docker compose logs -f controller               # Follow logs
docker compose down                             # Stop

# Legacy native (./install.sh first)
./run.sh                                        # Web GUI at http://localhost:8080
./run.sh --headless                             # Console-only mode
./run.sh --headless --rounds 1                  # Single round
./run.sh --port 9090                            # Custom port
./run.sh --headless --categories dns_filter,geo_ip
```

## Config

All settings in `config.json`, editable via the web GUI Configuration tab. In Docker Compose mode, config and logs live in `./data/` (bind-mounted, persists across container recreation). Sections: `generator`, `client_profiles`, `categories`, `legitimate_traffic`, `docker`.

## Requirements

- Ubuntu (install.sh handles all setup)
- Python 3.9+
- playwright, paramiko, fastapi, uvicorn, textual, docker, aiohttp (see requirements.txt)
