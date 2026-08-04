"""App Control — SSH block, Facebook reject, Gmail alert."""

import random
from . import TestCategory
from ..primitives import ssh_connect, web_request


class AppControl(TestCategory):
    name = "app_control"
    display_name = "App Control"

    async def run(self, context, config, source_ip=None):
        cat_config = config["categories"].get("app_control", {})
        results = []

        for target in cat_config.get("ssh_targets", []):
            result = await ssh_connect(target["host"], target.get("port", 22))
            result.category = self.name
            results.append(result)
            await _human_delay()

        for target in cat_config.get("web_targets", []):
            result = await web_request(target["url"], context)
            result.category = self.name
            results.append(result)
            await _human_delay()

        return results


async def _human_delay():
    import asyncio
    await asyncio.sleep(random.uniform(1, 3))
