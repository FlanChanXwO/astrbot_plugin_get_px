from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "check_astrbot_plugin_lifecycle.py"
WORKFLOW = ROOT / ".github" / "workflows" / "plugin-lifecycle.yml"


def _load_lifecycle_module():
    spec = importlib.util.spec_from_file_location("get_px_lifecycle", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载生命周期检查脚本: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_select_latest_stable_version_ignores_prereleases() -> None:
    module = _load_lifecycle_module()

    assert (
        module.select_latest_stable_version(
            ["v4.27.5", "v4.28.0-beta.1", "v4.27.4", "4.2.0"]
        )
        == "v4.27.5"
    )


def test_select_latest_stable_version_requires_a_formal_release() -> None:
    module = _load_lifecycle_module()

    try:
        module.select_latest_stable_version(["v4.28.0-beta.1", "nightly"])
    except ValueError as exc:
        assert "stable" in str(exc).lower()
    else:
        raise AssertionError("没有正式版标签时应明确失败")


def test_lifecycle_workflow_matches_plugin_contract() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "name: AstrBot plugin lifecycle" in workflow
    assert "pull_request:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in workflow
    assert "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065" in workflow
    assert 'python-version: "3.12"' in workflow
    assert "ASTRBOT_REPOSITORY: https://github.com/AstrBotDevs/AstrBot.git" in workflow
    assert "python -m compileall -q main.py checkin pixiv plugin_api tests" in workflow
    assert "python -m json.tool _conf_schema.json" in workflow
    assert "node --check pages/pluginCenter/app.js" in workflow
    assert "pytest -v" in workflow
    assert "scripts/ci/check_astrbot_plugin_lifecycle.py" in workflow
    assert "--plugin-name astrbot_plugin_get_px" in workflow
    assert "contents: write" not in workflow
