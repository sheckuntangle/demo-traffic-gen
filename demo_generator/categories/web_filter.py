"""Web Filter — block/reject/alert by URL category (marijuana, shopping, sports)."""

import random
from . import TestCategory
from ..primitives import web_request


class WebFilter(TestCategory):
    name = "web_filter"
    display_name = "Web Filter"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("web_filter", {})
        results = []

        for target in cat_config.get("targets", []):
            await context.clear_cookies()
            try:
                await context.clear_permissions()
            except Exception:
                pass
            result = await web_request(target["url"], context)
            result.category = self.name
            expected = target.get("expected", "")
            if expected:
                result.message = f"[expected: {expected}] {result.message}"
            results.append(result)
            await _human_delay()

        return results


async def _human_delay():
    import asyncio
    await asyncio.sleep(random.uniform(2, 5))
