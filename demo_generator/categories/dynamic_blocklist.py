"""Dynamic Blocklist — block/alert specific IPs and domains."""

import random
from . import TestCategory
from ..primitives import ping, tcp_connect, dns_query, web_request


class DynamicBlocklist(TestCategory):
    name = "dynamic_blocklist"
    display_name = "Dynamic Blocklist"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("dynamic_blocklist", {})
        results = []

        for target in cat_config.get("ip_targets", []):
            expected = target.get("expected", "")
            exp_tag = f"[expected: {expected}] " if expected else ""

            result = await ping(target["ip"], target.get("description", ""), source_ip=source_ip)
            result.category = self.name
            result.message = exp_tag + result.message
            results.append(result)
            await _delay()

            result = await tcp_connect(target["ip"], 80)
            result.category = self.name
            result.message = exp_tag + result.message
            results.append(result)
            await _delay()

        for target in cat_config.get("domain_targets", []):
            expected = target.get("expected", "")
            exp_tag = f"[expected: {expected}] " if expected else ""

            result = await dns_query(target["domain"])
            result.category = self.name
            result.message = exp_tag + result.message
            results.append(result)
            await _delay()

            url = f"https://{target['domain']}"
            result = await web_request(url, context)
            result.category = self.name
            result.message = exp_tag + result.message
            results.append(result)
            await _delay()

        return results


async def _delay():
    import asyncio
    await asyncio.sleep(random.uniform(1, 3))
