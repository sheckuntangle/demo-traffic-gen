# Traffic Generator for Firewall Demo

Generate realistic network traffic to populate firewall reporting for demonstration purposes.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
python3 -m playwright install chromium

# Run the traffic generator
python3 traffic_generator.py
```

## What It Does

This script generates various types of network traffic to simulate realistic firewall activity:

- **Ping Tests**: Tests connectivity to major DNS servers
- **DNS Queries**: Performs DNS lookups on both blocked and allowed domains
- **Web Requests**: Uses headless Chromium browser to visit websites (realistic traffic)
- **Geo-IP Tests**: Attempts connections to IPs from France and China

## Files

- `traffic_generator.py` - Main script
- `config.json` - Configuration file with all targets
- `requirements.txt` - Python dependencies
- `claude.md` - Detailed documentation

## Customization

Edit `config.json` to modify:
- DNS servers to ping
- Blocked/allowed domains
- Blocked/allowed websites
- Geo-IP test targets

## Output

Real-time color-coded results showing pass/fail status for each test, with summary statistics at the end.

See `claude.md` for detailed documentation.
