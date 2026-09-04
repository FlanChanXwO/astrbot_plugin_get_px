from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci.check_plugin_lifecycle import stage_plugin


@pytest.mark.parametrize(
    ("plugin_relative", "root_relative"),
    [
        ("plugin", "plugin/astrbot-root"),
        ("astrbot-root/plugin", "astrbot-root"),
    ],
)
def test_stage_plugin_rejects_containing_paths(
    tmp_path: Path,
    plugin_relative: str,
    root_relative: str,
) -> None:
    plugin_dir = tmp_path / plugin_relative
    astrbot_root = tmp_path / root_relative
    plugin_dir.mkdir(parents=True)
    astrbot_root.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ValueError, match="不能互相包含"):
        stage_plugin(
            plugin_dir=plugin_dir,
            astrbot_root=astrbot_root,
            plugin_name="example_plugin",
        )
