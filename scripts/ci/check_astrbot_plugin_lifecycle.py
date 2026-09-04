"""用官方 AstrBot PluginManager 验证插件的加载、卸载与资源清理。

脚本只用于 PR CI 或本地兼容性检查。它会把插件源码复制到临时
``ASTRBOT_ROOT``，再调用官方 ``PluginManager.load()``、``_terminate_plugin()``
和 ``_unbind_plugin()``。检查过程不连接真实平台，只写入临时配置和插件数据。
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import re
import shutil
import sys
import traceback
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


_STABLE_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CATCHABLE_ERRORS = (Exception, asyncio.CancelledError)
_EXCLUDED_NAMES = {
    ".git",
    ".github",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "Progress",
    "__pycache__",
    "data",
    "docs",
    "scripts",
    "tests",
}


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    """记录本轮检查前后的全局运行时对象身份。"""

    handlers: tuple[object, ...] = ()
    web_apis: tuple[object, ...] = ()
    tasks: tuple[asyncio.Task[Any], ...] = ()


@dataclass(slots=True)
class LifecycleRuntime:
    """官方 Context、PluginManager 和运行时快照函数。"""

    context: Any
    plugin_manager: Any
    snapshot_state: Callable[[], RuntimeSnapshot]


@dataclass(frozen=True, slots=True)
class LifecycleReport:
    """一次生命周期检查的可审计结果。"""

    astrbot_version: str
    plugin_name: str
    plugin_version: str
    handler_count: int
    registered_handler_count: int
    registered_web_api_count: int
    background_task_count: int
    terminate_succeeded: bool
    unbind_succeeded: bool
    resource_cleanup_succeeded: bool


class LifecycleCheckError(RuntimeError):
    """带有明确检查阶段的生命周期错误。"""

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(f"[{phase}] {message}")


def select_latest_stable_version(tags: Iterable[str]) -> str:
    """从标签中选择最高的正式三段式版本，排除 beta/rc 等预发布版本。"""

    candidates: list[tuple[tuple[int, int, int], str]] = []
    for raw_tag in tags:
        if not isinstance(raw_tag, str):
            continue
        tag = raw_tag.strip()
        match = _STABLE_VERSION_RE.fullmatch(tag)
        if match is None:
            continue
        candidates.append((tuple(int(part) for part in match.groups()), tag))
    if not candidates:
        raise ValueError("没有找到符合正式 stable 版本格式的 AstrBot release tag")
    return max(candidates, key=lambda item: item[0])[1]


def _is_excluded_name(name: str) -> bool:
    lowered = name.lower()
    excluded = {item.lower() for item in _EXCLUDED_NAMES}
    return name in _EXCLUDED_NAMES or lowered in excluded or name.startswith(".env")


def _validate_plugin_name(plugin_name: str) -> None:
    if _PLUGIN_NAME_RE.fullmatch(plugin_name) is None:
        raise ValueError(
            f"插件名必须是可导入的单一 Python 目录名，实际为 {plugin_name!r}"
        )


def _copy_plugin_tree(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for entry in sorted(source.iterdir(), key=lambda item: item.name):
        if _is_excluded_name(entry.name):
            continue
        if entry.is_symlink():
            # 不跟随可能指向仓库外或宿主机秘密的链接，避免 staging 越界。
            raise ValueError(f"插件源码包含不允许 staging 的符号链接: {entry}")
        target = destination / entry.name
        if entry.is_dir():
            _copy_plugin_tree(entry, target)
        elif entry.is_file():
            shutil.copy2(entry, target)
        else:
            raise OSError(f"无法 staging 非普通文件: {entry}")


def stage_plugin(
    *,
    plugin_dir: str | Path,
    astrbot_root: str | Path,
    plugin_name: str,
) -> Path:
    """把插件源码复制到临时 AstrBot 根目录。"""

    source = Path(plugin_dir).expanduser().resolve()
    root = Path(astrbot_root).expanduser().resolve()
    _validate_plugin_name(plugin_name)
    if not source.is_dir():
        raise ValueError(f"插件目录不存在或不是目录: {source}")
    if root == source or root in source.parents:
        raise ValueError("ASTRBOT_ROOT 不能位于插件源码目录内")
    if root.exists() and not root.is_dir():
        raise ValueError(f"ASTRBOT_ROOT 不是目录: {root}")
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"ASTRBOT_ROOT 必须为空的临时目录: {root}")

    destination = root / "data" / "plugins" / plugin_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    _copy_plugin_tree(source, destination)
    return destination


def _read_plugin_metadata(plugin_dir: Path, plugin_name: str) -> tuple[str, str]:
    metadata_path = next(
        (
            plugin_dir / filename
            for filename in ("metadata.yaml", "metadata.yml")
            if (plugin_dir / filename).is_file()
        ),
        None,
    )
    if metadata_path is None:
        raise LifecycleCheckError("metadata", "缺少 metadata.yaml 或 metadata.yml")

    try:
        # yaml 是 AstrBot 的运行时依赖；脚本在解析 stable tag 前不导入它。
        import yaml

        raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise LifecycleCheckError(
            "metadata",
            f"无法读取 {metadata_path.name}: {type(error).__name__}: {error}",
        ) from error
    if not isinstance(raw, Mapping):
        raise LifecycleCheckError("metadata", "metadata 必须解析为对象")

    name = raw.get("name")
    version = raw.get("version")
    astrbot_version = raw.get("astrbot_version")
    if not isinstance(name, str) or not name.strip():
        raise LifecycleCheckError("metadata", "metadata.name 不能为空")
    if name != plugin_name:
        raise LifecycleCheckError(
            "metadata",
            f"metadata.name={name!r} 与插件目录名 {plugin_name!r} 不一致",
        )
    if not isinstance(version, str) or not version.strip():
        raise LifecycleCheckError("metadata", "metadata.version 不能为空")
    if not isinstance(astrbot_version, str) or not astrbot_version.strip():
        raise LifecycleCheckError("metadata", "metadata.astrbot_version 不能为空")
    return version, astrbot_version


def _write_ci_plugin_config(astrbot_root: Path, plugin_name: str) -> None:
    config_path = astrbot_root / "data" / "config" / f"{plugin_name}_config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{}\n", encoding="utf-8")


def _prepend_sys_path(*paths: Path) -> list[str]:
    inserted: list[str] = []
    for path in paths:
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
            inserted.append(value)
    return inserted


def _remove_sys_path(values: Sequence[str]) -> None:
    for value in values:
        try:
            sys.path.remove(value)
        except ValueError:
            # 官方模块可能重排 sys.path；目标值不在列表时无需重复处理。
            continue


def _clear_directory_contents(directory: Path) -> None:
    """清理检查写入的目录内容，但保留调用方预先创建的空目录。"""

    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            entry.unlink()
        else:
            shutil.rmtree(entry)


def _build_official_context(context_cls: type[Any], config: Any) -> Any:
    """按官方 Context 的真实签名注入最小依赖，不自定义替代 Context。"""

    parameters = inspect.signature(context_cls).parameters
    kwargs: dict[str, Any] = {}
    for name, parameter in parameters.items():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        if name in {"self", "cls"}:
            continue
        if name in {"config", "astrbot_config"}:
            kwargs[name] = config
        elif parameter.default is inspect.Parameter.empty:
            # 生命周期检查不启动真实平台；Context 只保存这些宿主依赖。
            kwargs[name] = None
    if "config" not in kwargs and "astrbot_config" not in kwargs:
        raise TypeError("官方 Context 构造函数没有可识别的配置参数")
    return context_cls(**kwargs)


def _build_official_runtime(
    astrbot_source: Path,
    astrbot_root: Path,
    plugin_name: str,
) -> LifecycleRuntime:
    """建立官方 Context/PluginManager，并快照本轮运行时资源。"""

    _write_ci_plugin_config(astrbot_root, plugin_name)
    from astrbot.api.star import Context
    from astrbot.core import AstrBotConfig
    from astrbot.core.star.star_handler import star_handlers_registry
    from astrbot.core.star.star_manager import PluginManager

    config = AstrBotConfig(
        config_path=str(astrbot_root / "data" / "cmd_config.json"),
    )
    if isinstance(getattr(Context, "registered_web_apis", None), list):
        Context.registered_web_apis = []
    context = _build_official_context(Context, config)
    manager = PluginManager(context, config)

    def snapshot_state() -> RuntimeSnapshot:
        pending_tasks = tuple(task for task in asyncio.all_tasks() if not task.done())
        return RuntimeSnapshot(
            handlers=tuple(star_handlers_registry),
            web_apis=tuple(context.registered_web_apis),
            tasks=pending_tasks,
        )

    return LifecycleRuntime(
        context=context,
        plugin_manager=manager,
        snapshot_state=snapshot_state,
    )


def _find_metadata(runtime: LifecycleRuntime, plugin_name: str) -> Any | None:
    get_all_stars = getattr(runtime.context, "get_all_stars", None)
    if not callable(get_all_stars):
        raise LifecycleCheckError("registration", "官方 Context 缺少 get_all_stars()")
    stars = get_all_stars()
    if stars is None:
        raise LifecycleCheckError("registration", "官方 loader 未返回 Star registry")
    for metadata in reversed(tuple(stars)):
        if (
            getattr(metadata, "root_dir_name", None) == plugin_name
            or getattr(metadata, "name", None) == plugin_name
        ):
            return metadata
    return None


def _added(before: tuple[object, ...], after: tuple[object, ...]) -> tuple[object, ...]:
    before_ids = {id(item) for item in before}
    return tuple(item for item in after if id(item) not in before_ids)


def _delta(before: RuntimeSnapshot, after: RuntimeSnapshot) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        handlers=_added(before.handlers, after.handlers),
        web_apis=_added(before.web_apis, after.web_apis),
        tasks=tuple(
            task
            for task in _added(before.tasks, after.tasks)
            if isinstance(task, asyncio.Task) and not task.done()
        ),
    )


def _describe_handler(handler: object) -> str:
    for attribute in ("handler_full_name", "handler_name", "full_name", "name"):
        value = getattr(handler, attribute, None)
        if isinstance(value, str) and value:
            return value
    return type(handler).__name__


def _describe_web_api(api: object) -> str:
    if isinstance(api, tuple) and api:
        route = api[0]
        methods = api[2] if len(api) > 2 else None
        return f"{route!s} {methods!s}"
    return type(api).__name__


def _describe_task(task: asyncio.Task[Any]) -> str:
    name = task.get_name()
    coro = task.get_coro()
    code = getattr(coro, "cr_code", None)
    if code is not None:
        return f"{name}: {code.co_qualname} ({code.co_filename}:{code.co_firstlineno})"
    return f"{name}: {coro!r}"


def _assert_registration_is_observable(added: RuntimeSnapshot) -> None:
    missing: list[str] = []
    if not added.handlers:
        missing.append("handlers")
    if not added.web_apis:
        missing.append("web_apis")
    if missing:
        raise LifecycleCheckError(
            "registration",
            "lifecycle 没有观察到预期的运行时注册: " + ", ".join(missing),
        )


def _assert_no_runtime_residue(
    baseline: RuntimeSnapshot,
    final: RuntimeSnapshot,
) -> None:
    residue = _delta(baseline, final)
    details: list[str] = []
    if residue.handlers:
        details.append(
            "handlers="
            + ", ".join(_describe_handler(item) for item in residue.handlers)
        )
    if residue.web_apis:
        details.append(
            "web_apis="
            + ", ".join(_describe_web_api(item) for item in residue.web_apis)
        )
    if residue.tasks:
        details.append(
            "tasks=" + ", ".join(_describe_task(item) for item in residue.tasks)
        )
    if details:
        raise LifecycleCheckError(
            "resource cleanup",
            "插件卸载后仍存在本轮 lifecycle 新增的运行时资源: " + "; ".join(details),
        )


def _as_lifecycle_error(phase: str, error: BaseException) -> LifecycleCheckError:
    if isinstance(error, LifecycleCheckError):
        return error
    return LifecycleCheckError(
        phase,
        f"{type(error).__name__}: {error}",
    )


def _format_cleanup_errors(errors: list[tuple[str, BaseException]]) -> str:
    return "; ".join(
        f"{phase}: {type(error).__name__}: {error}" for phase, error in errors
    )


async def run_lifecycle_check(
    *,
    astrbot_source: str | Path,
    astrbot_version: str,
    plugin_dir: str | Path,
    astrbot_root: str | Path,
    plugin_name: str,
) -> LifecycleReport:
    """执行 load → official terminate → official unbind → residue check。"""

    source = Path(astrbot_source).expanduser().resolve()
    plugin = Path(plugin_dir).expanduser().resolve()
    root = Path(astrbot_root).expanduser().resolve()
    if not isinstance(astrbot_version, str) or not astrbot_version.strip():
        raise ValueError("AstrBot 版本标识不能为空")
    _validate_plugin_name(plugin_name)
    if not source.is_dir():
        raise ValueError(f"AstrBot 源码目录不存在或不是目录: {source}")

    root_was_present = root.exists()
    root_was_empty = (
        root_was_present
        and root.is_dir()
        and not root.is_symlink()
        and not any(root.iterdir())
    )
    runtime: LifecycleRuntime | None = None
    metadata: Any | None = None
    staged_plugin: Path | None = None
    baseline: RuntimeSnapshot | None = None
    report: LifecycleReport | None = None
    failure: LifecycleCheckError | None = None
    cleanup_errors: list[tuple[str, BaseException]] = []
    terminate_attempted = False
    terminate_succeeded = False
    unbind_attempted = False
    unbind_succeeded = False
    resource_cleanup_succeeded = False
    phase = "setup"
    previous_root = os.environ.get("ASTRBOT_ROOT")
    previous_reload = os.environ.get("ASTRBOT_RELOAD")
    inserted_paths: list[str] = []

    try:
        os.environ["ASTRBOT_ROOT"] = str(root)
        os.environ["ASTRBOT_RELOAD"] = "0"

        phase = "staging"
        staged_plugin = stage_plugin(
            plugin_dir=plugin,
            astrbot_root=root,
            plugin_name=plugin_name,
        )
        plugin_version, _plugin_astrbot_spec = _read_plugin_metadata(
            staged_plugin,
            plugin_name,
        )
        inserted_paths = _prepend_sys_path(root, source)

        phase = "runtime"
        runtime = _build_official_runtime(source, root, plugin_name)
        baseline = runtime.snapshot_state()

        phase = "load"
        load = getattr(runtime.plugin_manager, "load", None)
        if not callable(load):
            raise LifecycleCheckError("load", "官方 PluginManager 缺少 load()")
        load_result = await load(specified_dir_name=plugin_name)
        if not isinstance(load_result, tuple) or not load_result:
            raise LifecycleCheckError(
                "load",
                "官方 PluginManager.load() 返回值不是 (success, error) 元组",
            )
        if not bool(load_result[0]):
            detail = load_result[1] if len(load_result) > 1 else None
            raise LifecycleCheckError(
                "load",
                f"官方 PluginManager.load() 失败: {detail or '未提供错误信息'}",
            )

        phase = "registration"
        metadata = _find_metadata(runtime, plugin_name)
        if metadata is None:
            raise LifecycleCheckError(
                "registration",
                f"official loader 成功返回，但未发现已注册插件 {plugin_name}",
            )
        loaded_plugin = getattr(metadata, "star_cls", None)
        if loaded_plugin is None:
            raise LifecycleCheckError(
                "instantiation", f"插件 {plugin_name} 没有可用实例"
            )
        initialize = getattr(loaded_plugin, "initialize", None)
        if not callable(initialize):
            raise LifecycleCheckError("initialize", "插件实例没有 initialize()")

        loaded_snapshot = runtime.snapshot_state()
        registered = _delta(baseline, loaded_snapshot)
        _assert_registration_is_observable(registered)
        handler_count = len(getattr(metadata, "star_handler_full_names", ()))
        report = LifecycleReport(
            astrbot_version=astrbot_version,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            handler_count=handler_count,
            registered_handler_count=len(registered.handlers),
            registered_web_api_count=len(registered.web_apis),
            background_task_count=len(registered.tasks),
            terminate_succeeded=False,
            unbind_succeeded=False,
            resource_cleanup_succeeded=False,
        )

        phase = "terminate"
        terminate_attempted = True
        terminate = getattr(runtime.plugin_manager, "_terminate_plugin", None)
        if not callable(terminate):
            raise LifecycleCheckError(
                "terminate",
                "官方 PluginManager 缺少 _terminate_plugin()",
            )
        await terminate(metadata)
        terminate_succeeded = True

        phase = "unbind"
        unbind_attempted = True
        unbind = getattr(runtime.plugin_manager, "_unbind_plugin", None)
        module_path = getattr(metadata, "module_path", None)
        if not callable(unbind):
            raise LifecycleCheckError(
                "unbind", "官方 PluginManager 缺少 _unbind_plugin()"
            )
        if not isinstance(module_path, str) or not module_path:
            raise LifecycleCheckError("unbind", "插件 metadata.module_path 为空")
        await unbind(plugin_name, module_path)
        unbind_succeeded = True

        # 官方 terminate/unbind 已等待清理；让事件循环完成一个调度点后再取快照。
        await asyncio.sleep(0)
        phase = "resource cleanup"
        _assert_no_runtime_residue(baseline, runtime.snapshot_state())
        resource_cleanup_succeeded = True
    except _CATCHABLE_ERRORS as error:
        failure = _as_lifecycle_error(phase, error)
    finally:
        if runtime is not None:
            if metadata is None:
                try:
                    metadata = _find_metadata(runtime, plugin_name)
                except _CATCHABLE_ERRORS as error:
                    cleanup_errors.append(("registration", error))

            if metadata is not None:
                if not terminate_attempted:
                    terminate_attempted = True
                    try:
                        terminate = getattr(
                            runtime.plugin_manager, "_terminate_plugin", None
                        )
                        if not callable(terminate):
                            raise LifecycleCheckError(
                                "terminate",
                                "官方 PluginManager 缺少 _terminate_plugin()",
                            )
                        await terminate(metadata)
                        terminate_succeeded = True
                    except _CATCHABLE_ERRORS as error:
                        cleanup_errors.append(("terminate", error))

                if not unbind_attempted:
                    unbind_attempted = True
                    try:
                        unbind = getattr(runtime.plugin_manager, "_unbind_plugin", None)
                        module_path = getattr(metadata, "module_path", None)
                        if not callable(unbind):
                            raise LifecycleCheckError(
                                "unbind",
                                "官方 PluginManager 缺少 _unbind_plugin()",
                            )
                        if not isinstance(module_path, str) or not module_path:
                            raise LifecycleCheckError(
                                "unbind",
                                "插件 metadata.module_path 为空",
                            )
                        await unbind(plugin_name, module_path)
                        unbind_succeeded = True
                    except _CATCHABLE_ERRORS as error:
                        cleanup_errors.append(("unbind", error))

            if baseline is not None:
                try:
                    await asyncio.sleep(0)
                    _assert_no_runtime_residue(baseline, runtime.snapshot_state())
                    resource_cleanup_succeeded = True
                except _CATCHABLE_ERRORS as error:
                    cleanup_errors.append(("resource cleanup", error))

        _remove_sys_path(inserted_paths)
        if previous_root is None:
            os.environ.pop("ASTRBOT_ROOT", None)
        else:
            os.environ["ASTRBOT_ROOT"] = previous_root
        if previous_reload is None:
            os.environ.pop("ASTRBOT_RELOAD", None)
        else:
            os.environ["ASTRBOT_RELOAD"] = previous_reload

        if root.exists() and (root_was_empty or not root_was_present):
            try:
                if root_was_empty:
                    _clear_directory_contents(root)
                else:
                    shutil.rmtree(root)
            except _CATCHABLE_ERRORS as error:
                cleanup_errors.append(("temporary root cleanup", error))

    if failure is not None:
        if cleanup_errors:
            raise LifecycleCheckError(
                failure.phase,
                f"{failure}; cleanup failures: {_format_cleanup_errors(cleanup_errors)}",
            ) from failure
        raise failure
    if cleanup_errors:
        phase, error = cleanup_errors[0]
        raise LifecycleCheckError(
            phase,
            f"{type(error).__name__}: {error}; "
            f"additional cleanup failures: {_format_cleanup_errors(cleanup_errors[1:])}"
            if len(cleanup_errors) > 1
            else f"{type(error).__name__}: {error}",
        ) from error
    if report is None:
        raise LifecycleCheckError("unknown", "lifecycle 未生成检查报告")

    return replace(
        report,
        terminate_succeeded=terminate_succeeded,
        unbind_succeeded=unbind_succeeded,
        resource_cleanup_succeeded=resource_cleanup_succeeded,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用官方 AstrBot PluginManager 检查插件完整生命周期",
    )
    parser.add_argument("--astrbot-source", required=True, help="官方 AstrBot 源码目录")
    parser.add_argument(
        "--astrbot-version", required=True, help="被测 AstrBot 版本或 ref"
    )
    parser.add_argument("--plugin-dir", required=True, help="当前插件源码目录")
    parser.add_argument("--astrbot-root", required=True, help="临时 ASTRBOT_ROOT")
    parser.add_argument("--plugin-name", required=True, help="插件目录名")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    plugin_dir = Path(args.plugin_dir).expanduser().resolve()
    try:
        report = asyncio.run(
            run_lifecycle_check(
                astrbot_source=args.astrbot_source,
                astrbot_version=args.astrbot_version,
                plugin_dir=plugin_dir,
                astrbot_root=args.astrbot_root,
                plugin_name=args.plugin_name,
            )
        )
    except _CATCHABLE_ERRORS as error:
        print(
            f"{error}\n{traceback.format_exc()}",
            file=sys.stderr,
        )
        return 1

    print(
        "AstrBot plugin lifecycle passed: "
        f"astrbot={report.astrbot_version}, "
        f"plugin={report.plugin_name}@{report.plugin_version}, "
        f"handlers={report.registered_handler_count}, "
        f"web_apis={report.registered_web_api_count}, "
        f"background_tasks={report.background_task_count}, "
        "terminate=ok, unbind=ok, cleanup=ok"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
