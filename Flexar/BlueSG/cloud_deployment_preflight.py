"""Import smoke checks for the BlueSG Community Cloud deployment."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType


LOGGER = logging.getLogger(__name__)

REQUIRED_DEPLOYMENT_MODULES = (
    "pandas",
    "openpyxl",
    "pydeck",
    "Flexar.BlueSG.optimiser_config",
    "Flexar.BlueSG.optimiser_workflow_state",
    "Flexar.BlueSG.vehicle_route_optimiser_v2",
    "Flexar.BlueSG.v2_daily_roster_source",
)
REQUIRED_MODULE_EXPORTS = {
    "Flexar.BlueSG.optimiser_config": ("OPTIMISER_VERSION",),
    "Flexar.BlueSG.optimiser_workflow_state": (
        "begin_rider_draft",
        "cancel_rider_draft",
        "clear_import",
        "commit_optimiser_result",
        "initialise_workflow_state",
        "normalise_assignment_sequences",
        "normalise_riders",
        "refresh_stale_flag",
        "riders_for_optimizer",
        "riders_for_v2",
        "save_rider_draft",
        "streamlit_key_value_table",
        "validate_and_commit_job_import",
        "validate_assignment_draft",
        "validate_rider_draft",
    ),
    "Flexar.BlueSG.vehicle_route_optimiser_v2": (
        "V2OptimisationResult",
        "WorkStyle",
        "capacity_summary",
        "run_optimiser_v2",
        "validate_v2_roster",
    ),
    "Flexar.BlueSG.v2_daily_roster_source": (
        "DEFAULT_LOCAL_ROSTER",
        "load_daily_v2_roster",
        "save_local_v2_roster",
    ),
}


@dataclass(frozen=True)
class DeploymentImportFailure:
    """A safe-to-display summary of one failed deployment import."""

    requested_module: str
    error_type: str
    display_detail: str


def import_module_with_required_exports(
    module_name: str,
    required_exports: tuple[str, ...] = (),
    *,
    importer: Callable[[str], ModuleType] = importlib.import_module,
    reloader: Callable[[ModuleType], ModuleType] = importlib.reload,
) -> ModuleType:
    """Import a module and refresh it once if a hot update left it stale."""

    module = importer(module_name)
    missing_exports = [
        export_name
        for export_name in required_exports
        if not hasattr(module, export_name)
    ]
    if missing_exports:
        LOGGER.warning(
            "Reloading stale module %s; missing exports before reload: %s",
            module_name,
            ", ".join(missing_exports),
        )
        importlib.invalidate_caches()
        module = reloader(module)
        missing_exports = [
            export_name
            for export_name in required_exports
            if not hasattr(module, export_name)
        ]

    if missing_exports:
        raise ImportError(
            f"{module_name} is missing required exports after reload: "
            f"{', '.join(missing_exports)}"
        )
    return module


def check_deployment_imports(
    importer: Callable[[str], ModuleType] = importlib.import_module,
    reloader: Callable[[ModuleType], ModuleType] = importlib.reload,
) -> tuple[DeploymentImportFailure, ...]:
    """Import the Cloud runtime stack and return sanitised failures.

    Full tracebacks are written to the Cloud logs. The returned messages avoid
    exposing arbitrary exception content in the public error page.
    """

    failures: list[DeploymentImportFailure] = []
    for module_name in REQUIRED_DEPLOYMENT_MODULES:
        try:
            import_module_with_required_exports(
                module_name,
                REQUIRED_MODULE_EXPORTS.get(module_name, ()),
                importer=importer,
                reloader=reloader,
            )
        except ModuleNotFoundError as exc:
            missing_module = exc.name or module_name
            LOGGER.exception(
                "BlueSG deployment preflight could not find %s while importing %s",
                missing_module,
                module_name,
            )
            failures.append(
                DeploymentImportFailure(
                    requested_module=module_name,
                    error_type=type(exc).__name__,
                    display_detail=f"Missing module: {missing_module}",
                )
            )
        except ImportError as exc:
            LOGGER.exception(
                "BlueSG deployment preflight failed while importing %s",
                module_name,
            )
            failures.append(
                DeploymentImportFailure(
                    requested_module=module_name,
                    error_type=type(exc).__name__,
                    display_detail=(
                        f"Import failed inside {module_name}. See the Cloud logs "
                        "for the original exception."
                    ),
                )
            )
        except Exception as exc:  # pragma: no cover - defensive startup barrier
            LOGGER.exception(
                "BlueSG deployment preflight raised while importing %s",
                module_name,
            )
            failures.append(
                DeploymentImportFailure(
                    requested_module=module_name,
                    error_type=type(exc).__name__,
                    display_detail=(
                        f"Startup check failed inside {module_name}. See the Cloud "
                        "logs for the original exception."
                    ),
                )
            )
    return tuple(failures)
