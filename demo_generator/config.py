"""Configuration loading and validation."""

import json
import os
import sys


REQUIRED_CATEGORY_KEYS = {
    "app_control": ["ssh_targets", "web_targets"],
    "dns_filter": ["targets"],
    "geo_ip": ["countries"],
    "web_filter": ["targets"],
    "dynamic_blocklist": ["ip_targets", "domain_targets"],
    "security": ["targets"],
    "ip_reputation": ["targets"],
    "url_reputation": ["targets"],
}

GENERATOR_DEFAULTS = {
    "round_interval_seconds": 300,
    "legitimate_interval_seconds": 45,
    "max_rounds": 0,
    "client_count": 3,
    "dns_sample_range": [15, 25],
    "web_sample_range": [10, 20],
    "ping_sample_range": [2, 4],
    "interface": "",
    "log_dir": "./logs",
    "browser_recycle_rounds": 10,
}


def load_config(config_path="config.json"):
    if not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r") as f:
        config = json.load(f)

    config.setdefault("generator", {})
    for key, default in GENERATOR_DEFAULTS.items():
        config["generator"].setdefault(key, default)

    config.setdefault("client_profiles", [])
    config.setdefault("categories", {})
    config.setdefault("legitimate_traffic", {"dns_domains": [], "web_urls": [], "ping_targets": []})

    for cat_name in REQUIRED_CATEGORY_KEYS:
        if cat_name in config["categories"]:
            config["categories"][cat_name].setdefault("enabled", True)

    return config


def get_enabled_categories(config):
    return {
        name: cat_config
        for name, cat_config in config["categories"].items()
        if cat_config.get("enabled", False)
    }
