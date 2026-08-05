"""Security — block/alert specific IPs via security policy."""

import random
from . import TestCategory
from ..primitives import ping, tcp_connect, apply_expected


class Security(TestCategory):
    name = "security"
    display_name = "Security"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("security", {})
        results = []

        for target in cat_config.get("targets", []):
            expected = target.get("expected", "")

            result = await ping(target["ip"], target.get("description", ""), source_ip=source_ip)
            result.category = self.name
            apply_expected(result, expected)
            results.append(result)
            await _delay()

            result = await tcp_connect(target["ip"], 443)
            result.category = self.name
            apply_expected(result, expected)
            results.append(result)
            await _delay()

        return results


async def _delay():
    import asyncio
    await asyncio.sleep(random.uniform(1, 2))
