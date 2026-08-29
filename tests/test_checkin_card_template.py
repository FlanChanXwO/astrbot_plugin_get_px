import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "templates" / "checkin_themes" / "default"


class CheckinCardTemplateTest(unittest.TestCase):
    def test_required_h_paper_album_regions_exist(self):
        html = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
        css = (TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")

        for region in (
            "paper-sheet",
            "information-column",
            "artwork-frame",
            "rewards",
            "account-summary",
            "affection-progress",
            "artwork-credit",
        ):
            self.assertIn(f'class="{region}', html)

        self.assertIn("/*__CHECKIN_CARD_CSS__*/", html)
        self.assertIn("width: 960px", css)
        self.assertIn("height: 540px", css)
        self.assertIn("object-fit: contain", css)
        self.assertIn("object-position: center", css)
        self.assertIsNone(re.search(r"https?://", html + css))

    def test_runtime_template_embeds_local_css(self):
        from astrbot_plugin_get_px.checkin.card import get_checkin_card_template

        template = get_checkin_card_template()
        self.assertNotIn("/*__CHECKIN_CARD_CSS__*/", template)
        self.assertNotIn('href="./style.css"', template)
        self.assertNotIn("__CHECKIN_CARD_FONT_DATA__", template)
        self.assertIn(".paper-sheet", template)
        self.assertIn('url("data:font/woff2;base64,', template)
        self.assertIsNone(re.search(r"https?://", template))

    def test_local_font_asset_is_bundled_and_reasonably_sized(self):
        css = (TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")
        font_path = TEMPLATE_DIR / "fonts" / "LXGWWenKaiLite-GB2312.woff2"

        self.assertTrue(font_path.is_file())
        self.assertLess(font_path.stat().st_size, 2 * 1024 * 1024)
        self.assertIn("LXGW WenKai Lite", css)
        self.assertIn("__CHECKIN_CARD_FONT_DATA__", css)
        self.assertNotIn("STKaiti", css)
        self.assertNotIn("KaiTi", css)

    def test_only_artwork_credit_may_use_text_smaller_than_18px(self):
        css = (TEMPLATE_DIR / "style.css").read_text(encoding="utf-8")
        undersized: list[tuple[str, int]] = []
        for match in re.finditer(
            r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}", css, re.S
        ):
            selector = match.group("selector").strip()
            for size in re.findall(r"font-size:\s*(\d+)px", match.group("body")):
                pixels = int(size)
                if pixels < 18 and ".artwork-credit" not in selector:
                    undersized.append((selector, pixels))

        self.assertEqual(undersized, [])


if __name__ == "__main__":
    unittest.main()
