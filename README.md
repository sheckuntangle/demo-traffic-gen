# Firewall Demo Traffic Generator

Multi-client, long-running traffic generator for populating firewall reporting dashboards. Generates realistic traffic across 9 firewall service categories with a web-based GUI for control and monitoring.

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

A single Ubuntu server runs behind the firewall on the DHCP subnet. In **local mode**, all traffic comes from one IP. In **Docker mode**, each simulated client runs in its own container on a macvlan network, giving it a unique IP on the firewall's subnet.

## Quick Start

```bash
# Build and launch the self-contained Docker deployment
docker compose up --build -d

# Open the web GUI
# http://<docker-host>:8080

# Follow controller logs, then stop it when finished
docker compose logs -f controller
docker compose down
```

The controller runs with host networking so the UI can discover the Docker
host's real network interfaces for macvlan configuration. Port 8080 therefore
listens on all host interfaces; restrict it with the host firewall to trusted
administrators.

Runtime state lives in `./data/`: the first startup creates
`data/config.json` from `config.example.json`, the web UI saves changes there,
and logs are written to `data/logs/`. Keep this directory to preserve settings
across `docker compose down` and container recreation.

Docker client mode mounts `/var/run/docker.sock` into the controller so it can
build worker images and create macvlan networks and traffic containers. Access
to that socket is effectively host-root access; only run this deployment from a
trusted checkout on a trusted host.

### For Running Through Bastion Configured Test Beds

For running through Bastion configured test beds - add this iptables rule to
the bastion host. It forwards unused bastion TCP port `8080` to the Compose
host at TCP port `8080`.

The supplied NAT table does not use port `8080`; append this DNAT rule to its
existing `CONSOLE` chain (replace the example with the Compose host's LAN IP):

```bash
GENERATOR_HOST_IP=192.168.0.200
iptables -t nat -A CONSOLE -p tcp --dport 8080 -j DNAT --to-destination "${GENERATOR_HOST_IP}:8080"
```

Browse to `http://<bastion-ip>:8080` after the controller is running.

The existing `POSTROUTING` MASQUERADE rules provide the return path. If the
bastion's `FORWARD` policy or rules do not already allow this traffic, enable
forwarding and add the matching allow rule:

```bash
sysctl -w net.ipv4.ip_forward=1
iptables -C FORWARD -p tcp -d "${GENERATOR_HOST_IP}" --dport 8080 -j ACCEPT || iptables -A FORWARD -p tcp -d "${GENERATOR_HOST_IP}" --dport 8080 -j ACCEPT
```

Persist the rules using the bastion host's normal firewall-management method.

### Legacy Native Installation

The original Ubuntu-host workflow remains available when Docker is not the
deployment target:

```bash
./install.sh
./run.sh
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
| **Dynamic Blocklist** | wikipedia (block), OpenDNS 208.67.220.220 (reject), cnn (alert) — tied to external blocklist feeds |
| **Security** | 9.9.9.9/Quad9 (block), 1.1.1.1/Cloudflare (reject), 94.140.14.14/AdGuard (accept) |
| **IDPS** | Per-signature Suricata tests — 6 SIDs with configurable default/expected actions and individual curl scripts |
| **IP Reputation** | BrightCloud-flagged malicious IPs — block/reject/alert, per-target Docker client IP selection |
| **URL Reputation** | BrightCloud-flagged high-risk URLs — block/reject/alert, per-target Docker client IP selection |
| **Legitimate Traffic** | High-volume normal browsing, DNS, and pings for realistic reporting |

Each round interleaves blocked/alerted traffic with legitimate "allowed" traffic so the firewall dashboard shows a realistic mix.

## Multi-Client

The generator simulates multiple clients with different browser fingerprints (user agents, viewports, timezones).

### Docker Clients (recommended for source IP diversity)

For traffic to appear from different source IPs in firewall reports, use **Docker macvlan mode**. Each client runs in its own Docker container with a unique IP on the firewall's DHCP subnet. All traffic types (browser, DNS, ping, TCP, SSH) originate from that container's IP.

Setup via the web GUI Configuration tab after the Compose controller is
running:

1. Configure the parent interface, subnet, and gateway in the **Docker Clients** card
2. Add containers with names matching your client profiles and IPs from the subnet
3. Enable Docker client mode and start the traffic generator; the controller
   builds the worker image (one time), creates the macvlan and management
   networks, and starts the configured containers automatically

Each container runs its own Chromium instance (~512 MB RAM per container).

### IP Aliasing (legacy, ping-only)

IP aliasing adds secondary addresses to the host interface. This only affects `ping` traffic — browser, DNS, TCP, and SSH still use the host's primary IP. Use Docker mode instead for full source IP diversity.

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
  --categories LIST   Comma-separated category names to enable
  --log-dir PATH      Log output directory (default: from config)
```

### Examples

```bash
# Launch web GUI on custom port
./run.sh --port 9090

# Run headless with 5 rounds
./run.sh --headless --rounds 5 --interval 60

# Run only DNS filter and geo-IP categories
./run.sh --headless --categories dns_filter,geo_ip
```

## Web GUI

The web interface at `http://localhost:8080` provides:

- **Dashboard**: Start/Stop controls with three run modes (Full Run, Triggers Only, Legitimate Only), per-category stats cards with "Run Now" buttons, and a live log stream
- **Configuration**: Generator settings, Docker client config, per-category targets (add/remove IPs, URLs, domains, IDPS signatures), and legitimate traffic pools — all saved to config.json. Each section has a "Reset to Defaults" button, plus a global reset at the top of the page
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
- **docker**: macvlan client mode settings (interface, subnet, container IPs)

## IP & URL Reputation

The `ip_reputation` and `url_reputation` categories need IPs/URLs that your BrightCloud service classifies as malicious/high-risk. Each category ships with 3 entries (block, reject, alert) — some are placeholders. Update them by:

1. Check candidates at [BrightCloud Lookup](https://www.brightcloud.com/tools/url-ip-lookup.php)
2. Pull from public threat feeds: [abuse.ch Feodo Tracker](https://feodotracker.abuse.ch/), [Spamhaus DROP](https://www.spamhaus.org/drop/), [URLhaus](https://urlhaus.abuse.ch/)
3. Test against your firewall to confirm they trigger the expected blocks

These targets change over time — refresh periodically.

When Docker client mode is enabled, each reputation target can be assigned a specific Docker client IP via a dropdown in the Configuration tab. This controls which macvlan client sources the test traffic, allowing different targets to appear from different IPs in firewall reports.

## Files

```
config.json              # All targets and settings
requirements.txt         # Python dependencies
compose.yaml             # Docker-only controller deployment
Dockerfile.controller    # Web/headless controller image
Dockerfile               # Dynamically spawned Docker worker image
install.sh               # Legacy one-time Ubuntu host setup
run.sh                   # Legacy native launch wrapper
traffic_generator.py     # Legacy single-pass script (still works)
demo_generator/          # Multi-client package
├── __main__.py          # CLI entry point (--web default)
├── config.py            # Config loading and defaults
├── engine.py            # Round scheduler with run modes
├── clients.py           # Multi-client browser context pool
├── docker_clients.py    # Docker macvlan client pool
├── logger.py            # Dual console + file logging
├── stats.py             # Statistics tracking
├── primitives.py        # Async test functions (ping, DNS, web, SSH, TCP)
├── categories/          # Test category modules
│   ├── legitimate.py    # Allowed traffic generation
│   ├── app_control.py   # SSH, Facebook, Gmail
│   ├── dns_filter.py    # Domain blocking
│   ├── geo_ip.py        # Country-based IP blocking
│   ├── web_filter.py    # URL category filtering
│   ├── dynamic_blocklist.py  # IP/domain blocking with external blocklist feeds
│   ├── security.py          # Security rule ping/TCP tests
│   ├── idps.py              # Per-signature IDS/IPS testing
│   ├── ip_reputation.py
│   └── url_reputation.py
├── worker/              # Docker container worker service
│   └── service.py       # FastAPI app accepting category run commands
├── web/                 # FastAPI web GUI (default)
│   ├── server.py        # FastAPI app + uvicorn
│   ├── run_manager.py   # Engine lifecycle manager
│   ├── routes_api.py    # REST API + config reset + Docker endpoints
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
