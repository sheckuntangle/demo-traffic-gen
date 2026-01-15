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
- Anti-bot detection measures (stealth user agent, realistic headers, automation masking)
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
python3 -m playwright install chromium
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

### Log Files

A timestamped log file is automatically created for each run (format: `traffic_generator_YYYYMMDD_HHMMSS.log`). The log file contains:
- All test results without color codes
- Section headers marking different test phases
- Summary statistics
- Error messages if any

Log files are saved in the current working directory and can be used for:
- Long-term archival of test results
- Analysis and comparison of different runs
- Integration with other reporting tools

## Anti-Detection Features

The script includes several techniques to avoid bot detection and bypass common anti-automation measures:

### Browser Configuration
- **Automation flags disabled**: Removes `navigator.webdriver` and automation-controlled features
- **Realistic viewport**: 1920x1080 resolution
- **Updated user agent**: Chrome 131 on Linux
- **Locale/timezone**: en-US/America/New_York

### HTTP Headers
- Complete set of modern browser headers (Accept, Accept-Language, Accept-Encoding)
- Security headers (Sec-Fetch-Dest, Sec-Fetch-Mode, Sec-Fetch-Site, Sec-Fetch-User)
- Connection persistence and cache control

### JavaScript Masking
- Hides `navigator.webdriver` property
- Adds `chrome.runtime` object
- Simulates browser plugins
- Sets realistic language preferences

These features help bypass protection on sites like Bloomberg, Reuters, Salesforce, and StackOverflow that use sophisticated bot detection.
