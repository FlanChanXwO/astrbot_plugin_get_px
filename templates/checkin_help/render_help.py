"""Dev-only script: regenerate assets/checkin_help_v4.1.png via html_render.

画布宽度固定 1440，高度随内容自适应（full_page 截图、不传 clip）；
新增指令使内容变高时图片自动变高，不会再被固定尺寸裁切。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 仓库根目录不可作为包根导入自身
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from .help_template import _help_template  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "assets" / "checkin_help_v4.1.png"


async def _main() -> None:
    from astrbot_plugin_get_px.main import GetPxPlugin

    plugin = object.__new__(GetPxPlugin)
    html = _help_template()
    png_path = await plugin.html_render(
        html,
        {},
        return_url=False,
        options={
            "full_page": True,
            "type": "png",
            "viewport": {"width": 1440, "height": 1200},
            "animations": "disabled",
        },
    )
    # return_url=False 时会返回临时文件路径 str
    OUT.write_bytes(Path(str(png_path)).read_bytes())
    print(f"help image written: {OUT}")


if __name__ == "__main__":
    asyncio.run(_main())