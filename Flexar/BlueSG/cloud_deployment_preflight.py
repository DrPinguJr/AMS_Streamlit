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


@dataclass(frozen=True)
class DeploymentImportFailure:
    """A safe-to-display summary of one failed deployment import."""

    requested_module: str
    error_type: str
    display_detail: str


def check_deployment_imports(
    importer: Callable[[str], ModuleType] = importlib.import_module,
) -> tuple[DeploymentImportFailure, ...]:
    """Import the Cloud runtime stack and return sanitised failures.

    Full tracebacks are written to the Cloud logs. The returned messages avoid
    exposing arbitrary exception content in the public error page.
    """

    failures: list[DeploymentImportFailure] = []
    for module_name in REQUIRED_DEPLOYMENT_MODULES:
        try:
            importer(module_name)
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
