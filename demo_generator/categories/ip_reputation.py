"""IP Reputation — block/alert IPs flagged as malicious by BrightCloud."""

import random
from . import TestCategory
from ..primitives import ping, tcp_connect


class IpReputation(TestCategory):
    name = "ip_reputation"
    display_name = "IP Reputation"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("ip_reputation", {})
        results = []

        for target in cat_config.get("targets", []):
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

        return results


async def _delay():
    import asyncio
    await asyncio.sleep(random.uniform(1, 3))
