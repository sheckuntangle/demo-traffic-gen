#!/usr/bin/env python3
"""
Traffic Generator for Firewall Demo
Generates various types of network traffic to populate firewall reporting.
"""

import json
import subprocess
import time
import random
import socket
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def load_config(config_file='config.json'):
    """Load configuration from JSON file."""
    with open(config_file, 'r') as f:
        return json.load(f)


def log_result(test_type, target, status, message=''):
    """Print formatted test result."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    status_color = GREEN if status == 'PASS' else RED if status == 'FAIL' else YELLOW
    print(f"[{timestamp}] {BLUE}{test_type:20}{RESET} | {target:50} | {status_color}{status:4}{RESET} {message}")


def ping_test(ip, name):
    """Test ping connectivity to an IP address."""
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '2', ip],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            log_result('PING', f"{name} ({ip})", 'PASS')
            return True
        else:
            log_result('PING', f"{name} ({ip})", 'FAIL', 'No response')
            return False
    except subprocess.TimeoutExpired:
        log_result('PING', f"{name} ({ip})", 'FAIL', 'Timeout')
        return False
    except Exception as e:
        log_result('PING', f"{name} ({ip})", 'FAIL', str(e))
        return False


def dns_query_test(domain):
    """Test DNS resolution for a domain."""
    try:
        result = socket.gethostbyname(domain)
        log_result('DNS QUERY', domain, 'PASS', f'Resolved to {result}')
        return True
    except socket.gaierror:
        log_result('DNS QUERY', domain, 'FAIL', 'Resolution failed')
        return False
    except Exception as e:
        log_result('DNS QUERY', domain, 'FAIL', str(e))
        return False


def web_request_test(url, browser, timeout=30):
    """Test web request using Playwright."""
    try:
        page = browser.new_page()

        # Add random delay to simulate human behavior
        time.sleep(random.uniform(1, 3))

        # Navigate to the URL
        response = page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')

        if response and response.status < 400:
            log_result('WEB REQUEST', url, 'PASS', f'Status: {response.status}')
            success = True
        else:
            status = response.status if response else 'No response'
            log_result('WEB REQUEST', url, 'FAIL', f'Status: {status}')
            success = False

        page.close()
        return success

    except PlaywrightTimeoutError:
        log_result('WEB REQUEST', url, 'FAIL', 'Timeout')
        return False
    except Exception as e:
        log_result('WEB REQUEST', url, 'FAIL', str(e)[:50])
        return False


def http_request_to_ip(ip, description, browser, timeout=15):
    """Test HTTP request to an IP address."""
    url = f"http://{ip}"
    try:
        page = browser.new_page()
        response = page.goto(url, timeout=timeout * 1000, wait_until='domcontentloaded')

        if response and response.status < 400:
            log_result('GEO-IP WEB', f"{ip} ({description})", 'PASS', f'Status: {response.status}')
            success = True
        else:
            status = response.status if response else 'No response'
            log_result('GEO-IP WEB', f"{ip} ({description})", 'FAIL', f'Status: {status}')
            success = False

        page.close()
        return success

    except PlaywrightTimeoutError:
        log_result('GEO-IP WEB', f"{ip} ({description})", 'FAIL', 'Timeout')
        return False
    except Exception as e:
        log_result('GEO-IP WEB', f"{ip} ({description})", 'FAIL', str(e)[:50])
        return False


def run_traffic_tests():
    """Main function to run all traffic tests."""
    print(f"\n{BLUE}{'='*120}{RESET}")
    print(f"{BLUE}Traffic Generator for Firewall Demo{RESET}")
    print(f"{BLUE}{'='*120}{RESET}\n")

    # Load configuration
    config = load_config()

    # Statistics
    stats = {
        'ping': {'pass': 0, 'fail': 0},
        'dns': {'pass': 0, 'fail': 0},
        'web': {'pass': 0, 'fail': 0},
        'geoip': {'pass': 0, 'fail': 0}
    }

    # 1. Ping Tests to DNS Servers
    print(f"\n{YELLOW}>>> Starting PING tests to DNS servers{RESET}\n")
    for server in config['dns_servers']['targets']:
        result = ping_test(server['ip'], server['name'])
        stats['ping']['pass' if result else 'fail'] += 1
        time.sleep(random.uniform(0.5, 1.5))

    # 2. DNS Query Tests
    print(f"\n{YELLOW}>>> Starting DNS query tests (blocked domains){RESET}\n")
    for domain in config['dns_queries']['blocked']:
        result = dns_query_test(domain)
        stats['dns']['pass' if result else 'fail'] += 1
        time.sleep(random.uniform(0.3, 1))

    print(f"\n{YELLOW}>>> Starting DNS query tests (allowed domains){RESET}\n")
    # Test a random subset of allowed domains (10-15 to keep it reasonable)
    allowed_sample = random.sample(config['dns_queries']['allowed'], min(15, len(config['dns_queries']['allowed'])))
    for domain in allowed_sample:
        result = dns_query_test(domain)
        stats['dns']['pass' if result else 'fail'] += 1
        time.sleep(random.uniform(0.3, 1))

    # 3. Web Request Tests using Playwright
    print(f"\n{YELLOW}>>> Starting web request tests with Playwright{RESET}\n")

    with sync_playwright() as p:
        # Launch browser in headless mode
        browser = p.chromium.launch(headless=True)

        # Test blocked sites
        print(f"\n{YELLOW}>>> Testing blocked websites{RESET}\n")
        for url in config['web_requests']['blocked']:
            result = web_request_test(url, browser)
            stats['web']['pass' if result else 'fail'] += 1
            time.sleep(random.uniform(2, 5))

        # Test allowed sites (random subset)
        print(f"\n{YELLOW}>>> Testing allowed websites{RESET}\n")
        allowed_web_sample = random.sample(config['web_requests']['allowed'], min(20, len(config['web_requests']['allowed'])))
        for url in allowed_web_sample:
            result = web_request_test(url, browser)
            stats['web']['pass' if result else 'fail'] += 1
            time.sleep(random.uniform(2, 5))

        # 4. Geo-IP Block Tests
        print(f"\n{YELLOW}>>> Starting Geo-IP block tests (France){RESET}\n")
        for target in config['geoip_tests']['france']['targets']:
            # Ping test
            result = ping_test(target['ip'], f"France - {target['description']}")
            stats['geoip']['pass' if result else 'fail'] += 1
            time.sleep(random.uniform(1, 2))

            # HTTP test
            result = http_request_to_ip(target['ip'], target['description'], browser)
            stats['geoip']['pass' if result else 'fail'] += 1
            time.sleep(random.uniform(2, 4))

        print(f"\n{YELLOW}>>> Starting Geo-IP block tests (China){RESET}\n")
        for target in config['geoip_tests']['china']['targets']:
            # Ping test
            result = ping_test(target['ip'], f"China - {target['description']}")
            stats['geoip']['pass' if result else 'fail'] += 1
            time.sleep(random.uniform(1, 2))

            # HTTP test
            result = http_request_to_ip(target['ip'], target['description'], browser)
            stats['geoip']['pass' if result else 'fail'] += 1
            time.sleep(random.uniform(2, 4))

        browser.close()

    # Print summary statistics
    print(f"\n{BLUE}{'='*120}{RESET}")
    print(f"{BLUE}Test Summary{RESET}")
    print(f"{BLUE}{'='*120}{RESET}\n")

    total_pass = sum(s['pass'] for s in stats.values())
    total_fail = sum(s['fail'] for s in stats.values())
    total_tests = total_pass + total_fail

    print(f"{'PING Tests:':<20} {GREEN}{stats['ping']['pass']} passed{RESET}, {RED}{stats['ping']['fail']} failed{RESET}")
    print(f"{'DNS Query Tests:':<20} {GREEN}{stats['dns']['pass']} passed{RESET}, {RED}{stats['dns']['fail']} failed{RESET}")
    print(f"{'Web Request Tests:':<20} {GREEN}{stats['web']['pass']} passed{RESET}, {RED}{stats['web']['fail']} failed{RESET}")
    print(f"{'Geo-IP Tests:':<20} {GREEN}{stats['geoip']['pass']} passed{RESET}, {RED}{stats['geoip']['fail']} failed{RESET}")
    print(f"\n{'TOTAL:':<20} {GREEN}{total_pass} passed{RESET}, {RED}{total_fail} failed{RESET} out of {total_tests} tests")
    print(f"\n{BLUE}{'='*120}{RESET}\n")


if __name__ == '__main__':
    try:
        run_traffic_tests()
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Test interrupted by user{RESET}\n")
    except Exception as e:
        print(f"\n\n{RED}Error: {e}{RESET}\n")
