from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
from types import SimpleNamespace


REPOSITORY_ROOT = Path(__file__).parents[1]
BLUESG_DIR = REPOSITORY_ROOT / "Flexar" / "BlueSG"
STREAMLIT_ENTRYPOINT = BLUESG_DIR / "streamlit_app.py"
EXPECTED_PAGE_TARGETS = {
    "pages/create_optimised_vehicle_routes_page.py",
    "pages/review_map_and_manually_adjust_route_assignments_page.py",
}
EXPECTED_REQUIREMENTS = [
    "streamlit==1.57.0",
    "pandas==3.0.3",
    "openpyxl==3.1.5",
    "pydeck==0.9.2",
]


def _literal_streamlit_page_targets(source: str) -> list[str]:
    tree = ast.parse(source)
    targets: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if not (
            isinstance(function, ast.Attribute)
            and function.attr == "Page"
            and isinstance(function.value, ast.Name)
            and function.value.id == "st"
        ):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            target = node.args[0].value
            if isinstance(target, str):
                targets.append(target)
    return targets


def _non_comment_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_cloud_entrypoint_exposes_only_existing_bluesg_pages() -> None:
    source = STREAMLIT_ENTRYPOINT.read_text(encoding="utf-8")
    page_targets = _literal_streamlit_page_targets(source)

    assert set(page_targets) == EXPECTED_PAGE_TARGETS
    assert len(page_targets) == len(EXPECTED_PAGE_TARGETS)
    for target in page_targets:
        assert "\\" not in target, f"Cloud page paths must use forward slashes: {target}"
        assert not Path(target).is_absolute()
        assert (BLUESG_DIR / Path(*target.split("/"))).is_file()


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
        BLUESG_DIR / Path(*target.split("/")) for target in EXPECTED_PAGE_TARGETS
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

    assert token_widgets >= 2


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
