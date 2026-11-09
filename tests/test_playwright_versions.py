from pathlib import Path
from types import SimpleNamespace
import re
import unittest
from unittest.mock import Mock, patch

from demo_generator.docker_clients import (
    DockerClientPool, WORKER_PLAYWRIGHT_VERSION, WORKER_VERSION_LABEL,
)


class PlaywrightVersionTests(unittest.TestCase):
    def test_package_and_browser_images_match_worker_version(self):
        root = Path(__file__).resolve().parents[1]
        version = WORKER_PLAYWRIGHT_VERSION
        self.assertIn(f"playwright=={version}", (root / "requirements.txt").read_text().splitlines())
        for filename in ("Dockerfile", "Dockerfile.controller"):
            image_version = re.search(r"playwright/python:v([\d.]+)-", (root / filename).read_text()).group(1)
            self.assertEqual(image_version, version, filename)
        self.assertIn(f'LABEL {WORKER_VERSION_LABEL}="{version}"', (root / "Dockerfile").read_text())

    def test_legacy_or_mismatched_worker_images_require_rebuild(self):
        pool = DockerClientPool({"generator": {}, "docker": {}})
        pool._docker = Mock()
        class ImageNotFound(Exception):
            pass
        with patch.dict("sys.modules", {"docker.errors": SimpleNamespace(ImageNotFound=ImageNotFound)}):
            for labels, expected in (({}, False), ({WORKER_VERSION_LABEL: "1.65.0"}, False),
                                     ({WORKER_VERSION_LABEL: WORKER_PLAYWRIGHT_VERSION}, True)):
                pool._docker.images.get.return_value = SimpleNamespace(labels=labels)
                self.assertEqual(pool.image_exists(), expected)
            pool._docker.images.get.side_effect = ImageNotFound()
            self.assertFalse(pool.image_exists())
            pool._docker.images.get.side_effect = RuntimeError("Docker unavailable")
            with self.assertRaisesRegex(RuntimeError, "Docker unavailable"):
                pool.image_exists()
