"""URL Reputation — block/alert URLs flagged as high risk by BrightCloud."""

import random
from . import TestCategory
from ..primitives import web_request


class UrlReputation(TestCategory):
    name = "url_reputation"
    display_name = "URL Reputation"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("url_reputation", {})
        results = []

        for target in cat_config.get("targets", []):
            result = await web_request(target["url"], context)
            result.category = self.name
            results.append(result)
            await _delay()

        return results


async def _delay():
    import asyncio
    await asyncio.sleep(random.uniform(2, 5))
