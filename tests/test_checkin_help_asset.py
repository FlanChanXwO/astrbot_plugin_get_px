"""Regression tests for the T2I-generated checkin help image."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_get_px import main


def test_help_template_inlines_font_and_new_commands(tmp_path):
    from astrbot_plugin_get_px.templates.checkin_help.help_template import _help_template

    html = _help_template()
    assert "data:font/woff2;base64," in html  # 字体内联，无外部 URL
    assert "LXGWWenKai" in html
    for cmd in (
        "签到日历",
        "签到状态",
        "签到成就",
        "签到生日",
        "签到称号",
        "签到排行",
        "签到商店",
        "签到主题",
        "签到管理",
    ):
        assert cmd in html
    assert "签到我的" not in html  # 旧组不再出现在帮助图


def test_help_png_is_1440x1800_rgb():
    from PIL import Image

    with Image.open(main.CHECKIN_HELP_IMAGE) as img:
        assert img.size == (1440, 1800)
        assert img.mode == "RGB"