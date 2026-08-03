from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, MutableMapping

import pandas as pd

from Flexar.BlueSG.job_import_staging import (
    JobValidationResult,
    commit_staged_jobs,
    validate_staged_jobs,
)
from Flexar.BlueSG.vehicle_route_optimiser_v2 import (
    Rider,
    WorkStyle,
    normalise_v2_roster,
    validate_v2_roster,
)


RIDER_DRAFT_COLUMNS = [
    "Rider Name",
    "Start Location",
    "Start Zone",
    "Preferred",
    "Maximum",
    "Work Style",
    "End Requirement",
    "Active",
    # Compatibility aliases retained for V1 rollback and the route planner.
    "Maximum Jobs",
    "Rider Load",
]


@dataclass(frozen=True)
class RiderValidationResult:
    is_valid: bool
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssignmentValidationResult:
    is_valid: bool
    errors: tuple[str, ...] = ()
    duplicate_job_ids: tuple[str, ...] = ()
    missing_job_ids: tuple[str, ...] = ()
    unknown_job_ids: tuple[str, ...] = ()


def _clean(value: Any) -> str:
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip()
    return " ".join(str(value).split())


def streamlit_key_value_table(
    items: list[tuple[Any, Any]],
    *,
    key_column: str = "Current item",
    value_column: str = "Value",
) -> pd.DataFrame:
    """Build an Arrow-safe two-column table for live Streamlit diagnostics."""

    return pd.DataFrame(
        {
            key_column: pd.Series((_clean(key) for key, _ in items), dtype="string"),
            value_column: pd.Series((_clean(value) for _, value in items), dtype="string"),
        }
    )


def normalise_riders(rider_df: pd.DataFrame | None) -> pd.DataFrame:
    source = rider_df.copy(deep=True) if rider_df is not None else pd.DataFrame()
    if "Maximum Jobs" not in source and "Max Jobs" in source:
        source["Maximum Jobs"] = source["Max Jobs"]
    v2 = normalise_v2_roster(source)
    v2["Preferred"] = pd.to_numeric(v2["Preferred"], errors="coerce").astype("Int64")
    v2["Maximum"] = pd.to_numeric(v2["Maximum"], errors="coerce").astype("Int64")
    v2["Maximum Jobs"] = v2["Maximum"]
    v2["Rider Load"] = v2["Work Style"].map(
        {
            WorkStyle.LOCAL.value: "Low",
            WorkStyle.FLEXIBLE.value: "Medium",
            WorkStyle.AREA_LEAD.value: "Priority",
        }
    ).fillna("Medium")
    for column in ["Rider Name", "Start Location", "Start Zone", "Work Style", "End Requirement"]:
        v2[column] = v2[column].apply(_clean)
    v2["Active"] = v2["Active"].fillna(True).astype(bool)
    return v2.loc[:, RIDER_DRAFT_COLUMNS].reset_index(drop=True)


def validate_rider_draft(rider_df: pd.DataFrame) -> RiderValidationResult:
    operation_date = pd.Timestamp.now(tz="Asia/Singapore").date()
    validation = validate_v2_roster(normalise_v2_roster(rider_df), operation_date)
    return RiderValidationResult(validation.is_valid, tuple(validation.errors))


def riders_for_optimizer(rider_df: pd.DataFrame) -> pd.DataFrame:
    validation = validate_rider_draft(rider_df)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    riders = normalise_riders(rider_df)
    riders = riders[riders["Active"]].copy()
    riders = riders.rename(columns={"Maximum": "Max Jobs"})
    return riders[["Rider Name", "Start Location", "Start Zone", "Max Jobs", "Rider Load"]].reset_index(drop=True)


def riders_for_v2(rider_df: pd.DataFrame, operation_date: Any) -> list[Rider]:
    validation = validate_v2_roster(normalise_riders(rider_df), operation_date)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    return validation.riders


def initialise_workflow_state(state: MutableMapping[str, Any], initial_riders: pd.DataFrame) -> None:
    state.setdefault("imported_source_data", None)
    state.setdefault("job_draft", pd.DataFrame())
    state.setdefault("committed_jobs", pd.DataFrame())
    state.setdefault("committed_riders", normalise_riders(initial_riders))
    state.setdefault("rider_draft", None)
    state.setdefault("optimiser_result", None)
    state.setdefault("result_is_stale", False)


def begin_rider_draft(state: MutableMapping[str, Any]) -> pd.DataFrame:
    draft = normalise_riders(state.get("committed_riders"))
    state["rider_draft"] = draft.copy(deep=True)
    return draft


def cancel_rider_draft(state: MutableMapping[str, Any]) -> None:
    state["rider_draft"] = None


def save_rider_draft(state: MutableMapping[str, Any], draft: pd.DataFrame) -> bool:
    reconciled = draft.copy(deep=True)
    before = normalise_riders(state.get("committed_riders"))
    if {"Maximum", "Maximum Jobs"} <= set(reconciled.columns) and len(reconciled) == len(before):
        for index in reconciled.index:
            current_new = reconciled.at[index, "Maximum"]
            current_legacy = reconciled.at[index, "Maximum Jobs"]
            previous_new = before.at[index, "Maximum"]
            previous_legacy = before.at[index, "Maximum Jobs"]
            new_changed = not pd.isna(current_new) and current_new != previous_new
            legacy_changed = not pd.isna(current_legacy) and current_legacy != previous_legacy
            if legacy_changed and not new_changed:
                reconciled.at[index, "Maximum"] = current_legacy
            else:
                reconciled.at[index, "Maximum Jobs"] = current_new
    validation = validate_rider_draft(reconciled)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    normalised = normalise_riders(reconciled)
    changed = not before.equals(normalised)
    state["committed_riders"] = normalised.copy(deep=True)
    state["rider_draft"] = None
    if changed:
        state["result_is_stale"] = state.get("optimiser_result") is not None
    return changed


def commit_job_draft(state: MutableMapping[str, Any], draft: pd.DataFrame) -> bool:
    committed = commit_staged_jobs(draft)
    before = state.get("committed_jobs")
    before = before if isinstance(before, pd.DataFrame) else pd.DataFrame()
    changed = not before.reset_index(drop=True).equals(committed.reset_index(drop=True))
    state["committed_jobs"] = committed.copy(deep=True)
    state["job_draft"] = committed.copy(deep=True)
    if changed:
        state["result_is_stale"] = state.get("optimiser_result") is not None
    return changed


def validate_and_commit_job_import(
    state: MutableMapping[str, Any],
    draft: pd.DataFrame,
) -> tuple[JobValidationResult, bool]:
    """Validate an imported source and atomically replace committed jobs."""

    validation = validate_staged_jobs(draft)
    state["job_draft"] = validation.dataframe.copy(deep=True)
    if not validation.is_valid:
        return validation, False
    changed = commit_job_draft(state, validation.dataframe)
    return validation, changed


def clear_import(state: MutableMapping[str, Any]) -> None:
    state["imported_source_data"] = None
    state["job_draft"] = pd.DataFrame()


def dataframe_signature(dataframe: pd.DataFrame | None) -> str:
    if dataframe is None or dataframe.empty:
        return hashlib.sha256(b"[]").hexdigest()
    normalised = dataframe.copy()
    normalised.columns = [str(column) for column in normalised.columns]
    normalised = normalised.reindex(sorted(normalised.columns), axis=1).astype("string").fillna("")
    payload = normalised.to_dict("records")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def committed_input_signature(jobs: pd.DataFrame, riders: pd.DataFrame) -> str:
    return hashlib.sha256(
        f"{dataframe_signature(jobs)}|{dataframe_signature(normalise_riders(riders))}".encode("utf-8")
    ).hexdigest()


def commit_optimiser_result(
    state: MutableMapping[str, Any],
    result: Any,
    *,
    jobs: pd.DataFrame | None = None,
    riders: pd.DataFrame | None = None,
) -> None:
    committed_jobs = jobs if jobs is not None else state.get("committed_jobs")
    committed_riders = riders if riders is not None else state.get("committed_riders")
    state["optimiser_result"] = result
    state["optimiser_result_signature"] = committed_input_signature(
        committed_jobs, committed_riders
    )
    state["result_is_stale"] = False


def refresh_stale_flag(state: MutableMapping[str, Any]) -> bool:
    if state.get("optimiser_result") is None:
        state["result_is_stale"] = False
        return False
    current = committed_input_signature(
        state.get("committed_jobs"), state.get("committed_riders")
    )
    stale = current != state.get("optimiser_result_signature")
    state["result_is_stale"] = stale
    return stale


def validate_assignment_draft(
    assignment_df: pd.DataFrame,
    expected_job_ids: list[str] | tuple[str, ...] | set[str],
    rider_names: list[str] | tuple[str, ...] | set[str],
) -> AssignmentValidationResult:
    expected = {_clean(value) for value in expected_job_ids}
    allowed_riders = {_clean(value) for value in rider_names}
    errors: list[str] = []
    if "Job ID" not in assignment_df.columns:
        return AssignmentValidationResult(False, ("Assignment draft is missing Job ID.",))
    job_ids = assignment_df["Job ID"].apply(_clean)
    counts = job_ids.value_counts()
    duplicates = tuple(sorted(counts[counts > 1].index.tolist()))
    actual = set(job_ids)
    missing = tuple(sorted(expected - actual))
    unknown = tuple(sorted(actual - expected))
    if duplicates:
        errors.append("Each job must appear exactly once; duplicate jobs were found.")
    if missing:
        errors.append("Jobs disappeared from the assignment draft.")
    if unknown:
        errors.append("Unknown jobs were added to the assignment draft.")
    if "Rider" not in assignment_df.columns:
        errors.append("Assignment draft is missing Rider.")
    else:
        invalid_riders = sorted(
            set(assignment_df["Rider"].apply(_clean)) - allowed_riders
        )
        if invalid_riders:
            errors.append("Assignments contain an unknown or inactive rider.")
    if "Sequence" not in assignment_df.columns:
        errors.append("Assignment draft is missing Sequence.")
    else:
        sequences = pd.to_numeric(assignment_df["Sequence"], errors="coerce")
        if sequences.isna().any():
            errors.append("Every assignment sequence must be numeric.")
    return AssignmentValidationResult(
        not errors,
        tuple(errors),
        duplicates,
        missing,
        unknown,
    )


def normalise_assignment_sequences(assignment_df: pd.DataFrame) -> pd.DataFrame:
    output = assignment_df.copy(deep=True)
    output["_sequence"] = pd.to_numeric(output["Sequence"], errors="raise")
    output["_order"] = range(len(output))
    output = output.sort_values(["Rider", "_sequence", "_order"], kind="stable")
    output["Sequence"] = output.groupby("Rider").cumcount() + 1
    return output.drop(columns=["_sequence", "_order"]).reset_index(drop=True)
