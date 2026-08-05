"""Legitimate traffic — high-volume allowed DNS, web, and ping traffic for realistic reporting."""

import random
from . import TestCategory
from ..primitives import ping, dns_query, web_request, TestResult


class Legitimate(TestCategory):
    name = "legitimate"
    display_name = "Legitimate Traffic"

    async def run(self, context, config, source_ip=None):
        legit = config.get("legitimate_traffic", {})
        gen = config.get("generator", {})
        results = []

        dns_domains = legit.get("dns_domains", [])
        if dns_domains:
            dns_range = gen.get("dns_sample_range", [15, 25])
            sample_size = min(random.randint(dns_range[0], dns_range[1]), len(dns_domains))
            sample = random.sample(dns_domains, sample_size)
            results.append(TestResult(
                test_type="INFO", target=f"DNS queries ({len(sample)} domains)",
                success=True, message="Starting DNS phase", category=self.name,
            ))
            for domain in sample:
                result = await dns_query(domain)
                result.category = self.name
                results.append(result)
                await _dns_delay()

        web_urls = legit.get("web_urls", [])
        if web_urls:
            web_range = gen.get("web_sample_range", [10, 20])
            sample_size = min(random.randint(web_range[0], web_range[1]), len(web_urls))
            sample = random.sample(web_urls, sample_size)
            results.append(TestResult(
                test_type="INFO", target=f"Web requests ({len(sample)} URLs)",
                success=True, message="Starting web phase", category=self.name,
            ))
            for url in sample:
                result = await web_request(url, context)
                result.category = self.name
                results.append(result)
                await _web_delay()

        ping_targets = legit.get("ping_targets", [])
        if ping_targets:
            ping_range = gen.get("ping_sample_range", [2, 4])
            sample_size = min(random.randint(ping_range[0], ping_range[1]), len(ping_targets))
            sample = random.sample(ping_targets, sample_size)
            results.append(TestResult(
                test_type="INFO", target=f"Ping targets ({len(sample)} hosts)",
                success=True, message="Starting ping phase", category=self.name,
            ))
            for target in sample:
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
