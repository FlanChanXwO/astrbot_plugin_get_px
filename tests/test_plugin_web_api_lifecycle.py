from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_get_px.plugin_api.api import PluginWebApi  # noqa: E402


class _Context:
    def __init__(self) -> None:
        self.registered_web_apis: list[tuple[object, ...]] = []

    def register_web_api(
        self,
        route: str,
        handler: object,
        methods: list[str],
        description: str,
    ) -> None:
        self.registered_web_apis.append((route, handler, methods, description))


def test_unregister_removes_only_this_plugin_routes() -> None:
    context = _Context()
    plugin = SimpleNamespace(context=context)
    api = PluginWebApi(
        plugin,
        plugin_name="astrbot_plugin_get_px",
        log_prefix="[Test]",
        internal_error_message="internal",
    )

    api.register()
    other_handler = object()
    context.registered_web_apis.append(
        ("/other_plugin/ping", other_handler, ["GET"], "other")
    )

    api.unregister()

    assert context.registered_web_apis == [
        ("/other_plugin/ping", other_handler, ["GET"], "other")
    ]
    api.unregister()
    assert len(context.registered_web_apis) == 1


@pytest.mark.asyncio
async def test_terminate_resources_unregisters_web_api() -> None:
    from astrbot_plugin_get_px.main import GetPxPlugin

    plugin = object.__new__(GetPxPlugin)
    plugin.plugin_web_api = SimpleNamespace(unregister=Mock())
    plugin._holiday_refresh_task = None
    plugin.client = None
    plugin.lolicon_client = None
    plugin.downloader = SimpleNamespace(close=AsyncMock())
    plugin.checkin_greeting = SimpleNamespace(close=AsyncMock())
    plugin._last_request = {}
    plugin._checkin_flow_locks = {}
    plugin.image_index = None
    plugin.checkin_store = None

    await plugin._terminate_resources()

    plugin.plugin_web_api.unregister.assert_called_once_with()
