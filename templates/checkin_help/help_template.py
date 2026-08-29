"""Assemble the self-contained check-in help HTML (CSS + LXGW font inlined)."""

from __future__ import annotations

import base64
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parent
_FONT_PATH = (
    _TEMPLATE_DIR.parent
    / "checkin_themes"
    / "default"
    / "fonts"
    / "LXGWWenKaiLite-GB2312.woff2"
)
_HTML_MARKER = "/*__HELP_CSS__*/"
_FONT_MARKER = "__HELP_FONT_DATA__"


def _help_template() -> str:
    html = (_TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    css = "".join(
        (p.read_text(encoding="utf-8") + "\n")
        for p in sorted((_TEMPLATE_DIR).glob("*.css"))
    )
    font_data = base64.b64encode(_FONT_PATH.read_bytes()).decode("ascii")
    css = css.replace(_FONT_MARKER, font_data)
    if _HTML_MARKER not in html:
        raise RuntimeError("check-in help template is missing its CSS marker")
    return html.replace(_HTML_MARKER, css)