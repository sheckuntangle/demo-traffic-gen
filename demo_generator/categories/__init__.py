"""Test category base class and registry."""

from abc import ABC, abstractmethod

_REGISTRY = {}


class TestCategory(ABC):
    name: str = ""
    display_name: str = ""
    _on_result = None

    @abstractmethod
    async def run(self, context, config, source_ip=None):
        """Execute tests for this category. Returns list of TestResult."""

    def emit_result(self, result):
        if self._on_result:
            self._on_result(result)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if cls.name:
            _REGISTRY[cls.name] = cls


def get_category(name):
    return _REGISTRY.get(name)


def get_all_categories():
    return dict(_REGISTRY)


# Import all category modules to trigger registration
from . import (
    app_control,
    dns_filter,
    geo_ip,
    web_filter,
    dynamic_blocklist,
    security,
    ip_reputation,
    url_reputation,
    idps,
    legitimate,
)
