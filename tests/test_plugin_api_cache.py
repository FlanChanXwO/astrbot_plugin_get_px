from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import pytest
from quart import Quart

from plugin_api.api import PluginWebApi


@pytest.mark.asyncio
async def test_cache_storage_and_clear():
    with tempfile.TemporaryDirectory() as tmp_root:
        cache_dir = Path(tmp_root) / "card_cache"
        cache_dir.mkdir()
        test_card = cache_dir / "card_1.jpg"
        test_card.write_bytes(b"dummy_card_data_12345")

        # Create a get_px_ temp file in system temp
        fd, temp_img = tempfile.mkstemp(prefix="get_px_", suffix=".jpg")
        with open(fd, "wb") as f:
            f.write(b"dummy_temp_image_data_67890")

        plugin = SimpleNamespace(
            checkin_cache=SimpleNamespace(root=cache_dir),
            log_prefix="[Test]",
        )
        api = PluginWebApi(
            plugin,
            plugin_name="test_plugin",
            log_prefix="[Test]",
            internal_error_message="Error",
        )

        app = Quart(__name__)
        async with app.app_context():
            # 1. Test get stats
            response = await api.cache_storage()
            data = await response.get_json()
            assert data["success"] is True
            assert data["card_cache_bytes"] == len(b"dummy_card_data_12345")
            assert data["card_cache_count"] == 1
            assert data["temp_download_count"] >= 1
            assert data["total_count"] >= 2
            assert "KB" in data["total_human"] or "B" in data["total_human"]

            # 2. Test clear
            clear_response = await api.cache_storage_clear()
            clear_data = await clear_response.get_json()
            assert clear_data["success"] is True
            assert clear_data["freed_bytes"] >= len(b"dummy_card_data_12345") + len(b"dummy_temp_image_data_67890")
            assert clear_data["deleted_files"] >= 2
            assert not test_card.exists()
            assert not Path(temp_img).exists()

            # 3. Test after clear
            after_response = await api.cache_storage()
            after_data = await after_response.get_json()
            assert after_data["card_cache_count"] == 0
            assert after_data["card_cache_bytes"] == 0
