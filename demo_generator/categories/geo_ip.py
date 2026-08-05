"""Geo-IP — test connections to IPs in blocked/alerted countries."""

import random
from . import TestCategory
from ..primitives import ping, tcp_connect, apply_expected


class GeoIp(TestCategory):
    name = "geo_ip"
    display_name = "Geo-IP"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("geo_ip", {})
        results = []

        for country, country_config in cat_config.get("countries", {}).items():
            expected = country_config.get("expected", "")
            for target in country_config.get("targets", []):
                desc = f"{country.title()} - {target['description']}"

                result = await ping(target["ip"], desc, source_ip=source_ip)
                result.category = self.name
                apply_expected(result, expected)
                results.append(result)
                await _delay()

                result = await tcp_connect(target["ip"], 443, timeout=3)
                result.category = self.name
                apply_expected(result, expected)
                results.append(result)
                await _delay()

        return results


async def _delay():
    import asyncio
    await asyncio.sleep(random.uniform(0.5, 1.5))
