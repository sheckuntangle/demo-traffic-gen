# Firewall Demo Traffic Generator

## Project Purpose

Generates realistic multi-client network traffic behind a firewall to populate reporting dashboards. Designed for demo environments where a single Ubuntu server sits behind an NGFW/UTM appliance.

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

- **Engine** (`engine.py`) — round-based scheduler, fans out categories across clients concurrently
- **ClientPool** (`clients.py`) — manages Playwright browser contexts with different fingerprints
- **DockerClientPool** (`docker_clients.py`) — runs each client in a Docker container on a macvlan network for source IP diversity
- **Categories** (`categories/`) — each category (web_filter, dns_filter, etc.) implements `TestCategory.run()` returning `TestResult` list
- **Primitives** (`primitives.py`) — async test functions: `web_request`, `ping`, `dns_query`, `tcp_connect`, `ssh_connect`
- **Web UI** (`web/`) — FastAPI + vanilla JS SPA with Dashboard and Configuration tabs
- **Worker** (`worker/service.py`) — lightweight FastAPI app running inside Docker containers, executes categories remotely

## Key Patterns

**Adding a category**: Create a new file in `categories/`, subclass `TestCategory`, set `name` and `display_name` class attrs, implement `async def run()`. Registration is automatic via `__init_subclass__`. Add import to `categories/__init__.py`.

**Client dispatch**: Engine calls `client.run_category(category, config)`. For local clients (`ClientContext`), this calls `category.run()` directly. For Docker clients (`DockerClient`), this POSTs to the container's worker API. The engine doesn't know which type it's using.

**Docker dual-network**: Containers attach to both a macvlan network (test traffic, real IPs) and a bridge network (management API). The host can't reach macvlan IPs directly due to L2 isolation.

## Commands

```bash
./install.sh              # One-time setup (system deps, venv, Docker, Playwright)
./run.sh                  # Web GUI at http://localhost:8080
./run.sh --headless       # Console-only mode
```

## Config

All settings in `config.json`, editable via the web GUI Configuration tab. Sections: `generator`, `client_profiles`, `categories`, `legitimate_traffic`, `docker`.
