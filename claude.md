# Traffic Generator for Firewall Demo

## Purpose
Generate realistic network traffic to populate firewall reporting for demonstration purposes.

## Components

### 1. Configuration File (config.json)
Contains all target domains, IPs, and DNS servers organized by category:
- DNS servers for ping testing
- Domains for DNS queries (blocked and allowed)
- Websites for HTTP requests (blocked and allowed)
- Geo-IP test IPs from France and China

### 2. Main Script (traffic_generator.py)
Python script using Playwright for realistic browser-based traffic generation.

## Traffic Types

1. **Ping Traffic**: Test connectivity to DNS servers (9.9.9.9, Google DNS, OpenDNS)
2. **DNS Queries**: Test DNS resolution with blocked (msn.com, yahoo.com) and allowed domains
3. **Web Requests**: Realistic browser traffic using Playwright headless mode to blocked (facebook.com, gmail.com) and 30-40 allowed sites
4. **Geo-IP Blocks**: Test connections to IPs from France and China

## Features
- Headless browser rendering for realistic traffic patterns
- Real-time pass/fail logging for each request
- Geographic diversity in target domains (30-40 sites from various countries)
- Separate configuration file for easy updates

## Requirements
- Python 3.x
- Playwright
- Standard library modules (subprocess, socket, json, time, random, datetime)

## Installation

1. Install Python dependencies:
```bash
pip install playwright
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

Run the traffic generator:
```bash
python3 traffic_generator.py
```

The script will:
1. Ping DNS servers (Quad9, Google DNS, OpenDNS)
2. Perform DNS queries on blocked and allowed domains
3. Generate web traffic using headless Chromium to blocked and allowed sites
4. Test geo-IP blocks by accessing IPs from France and China
5. Display real-time pass/fail results for each test
6. Show summary statistics at the end

## Configuration

Edit `config.json` to customize:
- DNS servers to ping
- Blocked/allowed domains for DNS queries
- Blocked/allowed URLs for web requests
- Geo-IP test targets

## Output

The script provides color-coded output:
- Timestamp for each test
- Test type (PING, DNS QUERY, WEB REQUEST, GEO-IP WEB)
- Target (domain/IP)
- Status (PASS/FAIL)
- Additional details (response codes, error messages)

Summary statistics are displayed at the end showing total passes/fails per category.
