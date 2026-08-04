"""Legitimate traffic — high-volume allowed DNS, web, and ping traffic for realistic reporting."""

import random
from . import TestCategory
from ..primitives import ping, dns_query, web_request


class Legitimate(TestCategory):
    name = "legitimate"
    display_name = "Legitimate Traffic"

    async def run(self, context, config, source_ip=None):
        legit = config.get("legitimate_traffic", {})
        results = []

        dns_domains = legit.get("dns_domains", [])
        if dns_domains:
            sample_size = min(random.randint(15, 25), len(dns_domains))
            for domain in random.sample(dns_domains, sample_size):
                result = await dns_query(domain)
                result.category = self.name
                results.append(result)
                await _dns_delay()

        web_urls = legit.get("web_urls", [])
        if web_urls:
            sample_size = min(random.randint(10, 20), len(web_urls))
            for url in random.sample(web_urls, sample_size):
                result = await web_request(url, context)
                result.category = self.name
                results.append(result)
                await _web_delay()

        ping_targets = legit.get("ping_targets", [])
        if ping_targets:
            sample_size = min(random.randint(2, 4), len(ping_targets))
            for target in random.sample(ping_targets, sample_size):
                result = await ping(target["ip"], target.get("name", ""), source_ip=source_ip)
                result.category = self.name
                results.append(result)
                await _ping_delay()

        return results


async def _dns_delay():
    import asyncio
    await asyncio.sleep(random.uniform(0.3, 1.0))


async def _web_delay():
    import asyncio
    await asyncio.sleep(random.uniform(2, 5))


async def _ping_delay():
    import asyncio
    await asyncio.sleep(random.uniform(0.5, 1.5))
