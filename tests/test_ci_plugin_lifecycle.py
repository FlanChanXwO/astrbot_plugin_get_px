from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


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


def test_run_lifecycle_check_cleans_preexisting_empty_root(
    monkeypatch, tmp_path: Path
) -> None:
    module = _load_lifecycle_module()
    astrbot_source = tmp_path / "astrbot"
    astrbot_source.mkdir()
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    astrbot_root = tmp_path / "astrbot-root"
    astrbot_root.mkdir()

    metadata = SimpleNamespace(
        star_cls=SimpleNamespace(initialize=lambda: None),
        module_path="main.py",
        root_dir_name="astrbot_plugin_get_px",
        name="astrbot_plugin_get_px",
        star_handler_full_names=("handler",),
    )
    handler = object()
    web_api = ("/ci", object(), ("GET",))
    snapshots = iter(
        (
            module.RuntimeSnapshot(),
            module.RuntimeSnapshot(handlers=(handler,), web_apis=(web_api,)),
            module.RuntimeSnapshot(),
            module.RuntimeSnapshot(),
        )
    )

    class FakePluginManager:
        async def load(self, **_kwargs):
            return True, None

        async def _terminate_plugin(self, _metadata):
            return None

        async def _unbind_plugin(self, _plugin_name, _module_path):
            return None

    runtime = module.LifecycleRuntime(
        context=object(),
        plugin_manager=FakePluginManager(),
        snapshot_state=lambda: next(snapshots),
    )
    monkeypatch.setattr(
        module,
        "_read_plugin_metadata",
        lambda _plugin_dir, _plugin_name: ("v3.6.1", ">=4"),
    )
    monkeypatch.setattr(module, "_prepend_sys_path", lambda *_paths: [])
    monkeypatch.setattr(
        module, "_build_official_runtime", lambda *_args, **_kwargs: runtime
    )
    monkeypatch.setattr(module, "_find_metadata", lambda *_args: metadata)

    asyncio.run(
        module.run_lifecycle_check(
            astrbot_source=astrbot_source,
            astrbot_version="v4.27.5",
            plugin_dir=plugin_dir,
            astrbot_root=astrbot_root,
            plugin_name="astrbot_plugin_get_px",
        )
    )

    assert astrbot_root.is_dir()
    assert not any(astrbot_root.iterdir())


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
    assert "python -m pytest -v" in workflow
    assert "\n          pytest -v\n" not in workflow
    assert "scripts/ci/check_astrbot_plugin_lifecycle.py" in workflow
    assert "--plugin-name astrbot_plugin_get_px" in workflow
    assert "contents: write" not in workflow
