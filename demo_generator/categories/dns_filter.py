"""DNS Filter — block/reject/alert specific domains."""

import random
from . import TestCategory
from ..primitives import dns_query


class DnsFilter(TestCategory):
    name = "dns_filter"
    display_name = "DNS Filter"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("dns_filter", {})
        results = []

        for target in cat_config.get("targets", []):
            result = await dns_query(target["domain"])
            result.category = self.name
            expected = target.get("expected", "")
            if expected:
                result.message = f"[expected: {expected}] {result.message}"
            results.append(result)
            await _human_delay()

        return results


async def _human_delay():
    import asyncio
    await asyncio.sleep(random.uniform(0.3, 1.0))
