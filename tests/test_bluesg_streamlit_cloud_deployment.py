from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


REPOSITORY_ROOT = Path(__file__).parents[1]
BLUESG_DIR = REPOSITORY_ROOT / "Flexar" / "BlueSG"
STREAMLIT_ENTRYPOINT = BLUESG_DIR / "streamlit_app.py"
ROOT_ENTRYPOINT = REPOSITORY_ROOT / "app.py"
SHARED_ROUTER = BLUESG_DIR / "cloud_streamlit_router.py"
EXPECTED_PAGE_TARGETS = {
    "create_optimised_vehicle_routes_page.py",
    "hourly_route_optimiser_page.py",
    "review_map_and_manually_adjust_route_assignments_page.py",
}
EXPECTED_REQUIREMENTS = [
    "streamlit==1.57.0",
    "starlette==1.3.1",
    "pandas==3.0.3",
    "openpyxl==3.1.5",
    "pydeck==0.9.2",
]


def _page_filename_constants(source: str) -> list[str]:
    tree = ast.parse(source)
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.endswith("_page.py"):
                targets.append(node.value)
    return targets


def _non_comment_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_cloud_entrypoint_exposes_only_existing_bluesg_pages() -> None:
    source = SHARED_ROUTER.read_text(encoding="utf-8")
    page_targets = _page_filename_constants(source)

    assert set(page_targets) == EXPECTED_PAGE_TARGETS
    assert len(page_targets) == len(EXPECTED_PAGE_TARGETS)
    for target in page_targets:
        assert (BLUESG_DIR / "pages" / target).is_file()


def test_dedicated_entrypoint_uses_the_bluesg_router() -> None:
    dedicated_source = STREAMLIT_ENTRYPOINT.read_text(encoding="utf-8")

    assert "run_bluesg_cloud_app" in dedicated_source


def test_root_entrypoint_keeps_full_navigation_behind_cloud_access() -> None:
    root_source = ROOT_ENTRYPOINT.read_text(encoding="utf-8")

    assert "require_cloud_access()" in root_source
    assert "run_bluesg_cloud_app" not in root_source
    for navigation_group in ("Home", "Lance", "Flexar", "Contracts", "HR"):
        assert f'"{navigation_group}"' in root_source


def test_cloud_preflight_smoke_imports_the_deployment_stack() -> None:
    preflight = importlib.import_module("Flexar.BlueSG.cloud_deployment_preflight")

    assert preflight.check_deployment_imports() == ()


def test_cloud_preflight_sanitises_missing_dependency_errors() -> None:
    preflight = importlib.import_module("Flexar.BlueSG.cloud_deployment_preflight")

    def missing_importer(module_name: str):
        error = ModuleNotFoundError("sensitive arbitrary exception text")
        error.name = "example_missing_dependency"
        raise error

    failures = preflight.check_deployment_imports(importer=missing_importer)

    assert len(failures) == len(preflight.REQUIRED_DEPLOYMENT_MODULES)
    assert all(
        failure.display_detail == "Missing module: example_missing_dependency"
        for failure in failures
    )
    assert all(
        "sensitive arbitrary exception text" not in failure.display_detail
        for failure in failures
    )


def test_cloud_preflight_reloads_a_module_missing_required_exports() -> None:
    preflight = importlib.import_module("Flexar.BlueSG.cloud_deployment_preflight")
    stale_module = ModuleType("example_module")
    refreshed_module = ModuleType("example_module")
    refreshed_module.required_symbol = object()
    reload_calls: list[ModuleType] = []

    def importer(module_name: str) -> ModuleType:
        assert module_name == "example_module"
        return stale_module

    def reloader(module: ModuleType) -> ModuleType:
        reload_calls.append(module)
        return refreshed_module

    loaded_module = preflight.import_module_with_required_exports(
        "example_module",
        ("required_symbol",),
        importer=importer,
        reloader=reloader,
    )

    assert loaded_module is refreshed_module
    assert reload_calls == [stale_module]


def test_cloud_preflight_rejects_exports_still_missing_after_reload() -> None:
    preflight = importlib.import_module("Flexar.BlueSG.cloud_deployment_preflight")
    stale_module = ModuleType("example_module")

    with pytest.raises(ImportError, match="required_symbol"):
        preflight.import_module_with_required_exports(
            "example_module",
            ("required_symbol",),
            importer=lambda module_name: stale_module,
            reloader=lambda module: module,
        )


def test_optimizer_page_guards_named_imports_against_stale_modules() -> None:
    page_source = (
        BLUESG_DIR / "pages" / "create_optimised_vehicle_routes_page.py"
    ).read_text(encoding="utf-8")

    assert "import_module_with_required_exports" in page_source
    assert "REQUIRED_MODULE_EXPORTS[_module_name]" in page_source


def test_cloud_requirements_are_minimal_and_exactly_pinned() -> None:
    requirements = _non_comment_lines(BLUESG_DIR / "requirements.txt")

    assert requirements == EXPECTED_REQUIREMENTS
    assert all("==" in requirement for requirement in requirements)


def test_example_secrets_are_safe_placeholders() -> None:
    import tomllib

    example_path = REPOSITORY_ROOT / ".streamlit" / "secrets.toml.example"
    example = tomllib.loads(example_path.read_text(encoding="utf-8"))
    expected_keys = {"APP_PASSWORD", "ONEMAP_EMAIL", "ONEMAP_PASSWORD"}

    assert expected_keys <= set(example)
    for key in expected_keys:
        value = example[key]
        assert isinstance(value, str) and value.strip()
        lowered = value.casefold()
        assert any(
            marker in lowered
            for marker in ("your", "replace", "change", "example", "placeholder")
        ), f"{key} must contain an unmistakable placeholder, not a real secret"


def test_gitignore_protects_nested_secrets_and_mutable_bluesg_data() -> None:
    rules = {
        line.replace("\\", "/")
        for line in _non_comment_lines(REPOSITORY_ROOT / ".gitignore")
    }

    assert {
        "**/.env",
        "**/.env.*",
        "!**/.env.example",
        "**/.streamlit/secrets.toml",
        "Flexar/BlueSG/data/cache/runtime/",
        "Flexar/BlueSG/data/weekday_rider_availability_and_capacity_roster.xlsx",
    } <= rules


def test_onemap_token_widgets_never_prefill_configured_secrets() -> None:
    page_paths = [
        BLUESG_DIR / "pages" / target for target in EXPECTED_PAGE_TARGETS
    ]
    token_widgets = 0

    for page_path in page_paths:
        tree = ast.parse(page_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not (
                isinstance(function, ast.Attribute)
                and function.attr == "text_input"
                and isinstance(function.value, ast.Name)
                and function.value.id == "st"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and "onemap" in node.args[0].value.casefold()
                and "token" in node.args[0].value.casefold()
            ):
                continue

            token_widgets += 1
            value_keywords = [
                keyword.value for keyword in node.keywords if keyword.arg == "value"
            ]
            assert not value_keywords or all(
                isinstance(value, ast.Constant) and value.value == ""
                for value in value_keywords
            ), f"{page_path.name} must leave OneMap token inputs blank"

    # The optimiser now authenticates automatically from secrets. A manual
    # token field remains only where an operational page still supports it.
    assert token_widgets >= 1


def test_cloud_login_policy_defaults_by_platform_and_accepts_override(
    monkeypatch,
) -> None:
    access_control = importlib.import_module("Flexar.BlueSG.cloud_access_control")
    monkeypatch.delenv("BLUESG_REQUIRE_LOGIN", raising=False)

    windows_os = SimpleNamespace(
        name="nt",
        environ=os.environ,
        getenv=os.getenv,
    )
    linux_os = SimpleNamespace(
        name="posix",
        environ=os.environ,
        getenv=os.getenv,
    )

    monkeypatch.setattr(access_control, "os", windows_os)
    assert access_control.cloud_login_required() is False

    monkeypatch.setattr(access_control, "os", linux_os)
    assert access_control.cloud_login_required() is True

    monkeypatch.setenv("BLUESG_REQUIRE_LOGIN", "false")
    assert access_control.cloud_login_required() is False

    monkeypatch.setattr(access_control, "os", windows_os)
    monkeypatch.setenv("BLUESG_REQUIRE_LOGIN", "true")
    assert access_control.cloud_login_required() is True
