"""Geo-IP — test connections to IPs in blocked/alerted countries."""

import random
from . import TestCategory
from ..primitives import ping, http_to_ip


class GeoIp(TestCategory):
    name = "geo_ip"
    display_name = "Geo-IP"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("geo_ip", {})
        results = []

        for country, country_config in cat_config.get("countries", {}).items():
            for target in country_config.get("targets", []):
                desc = f"{country.title()} - {target['description']}"

                result = await ping(target["ip"], desc, source_ip=source_ip)
                result.category = self.name
                results.append(result)
                await _short_delay()

                result = await http_to_ip(target["ip"], desc, context)
                result.category = self.name
                results.append(result)
                await _long_delay()

        return results


async def _short_delay():
    import asyncio
    await asyncio.sleep(random.uniform(1, 2))


async def _long_delay():
    import asyncio
    await asyncio.sleep(random.uniform(2, 4))
