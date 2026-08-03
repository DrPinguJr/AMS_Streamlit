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


RIDER_DRAFT_COLUMNS = [
    "Rider Name",
    "Start Location",
    "Start Zone",
    "Maximum Jobs",
    "Rider Load",
    "Active",
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
    riders = rider_df.copy(deep=True) if rider_df is not None else pd.DataFrame()
    if "Maximum Jobs" not in riders.columns and "Max Jobs" in riders.columns:
        riders["Maximum Jobs"] = riders["Max Jobs"]
    defaults = {
        "Rider Name": "",
        "Start Location": "",
        "Start Zone": "",
        "Maximum Jobs": None,
        "Rider Load": "Medium",
        "Active": True,
    }
    for column, default in defaults.items():
        if column not in riders.columns:
            riders[column] = default
    riders = riders.loc[:, RIDER_DRAFT_COLUMNS].copy()
    for column in ["Rider Name", "Start Location", "Start Zone", "Rider Load"]:
        riders[column] = riders[column].apply(_clean)
    riders["Rider Load"] = riders["Rider Load"].replace({"Normal": "Medium", "Piority": "Priority"})
    riders["Maximum Jobs"] = pd.to_numeric(riders["Maximum Jobs"], errors="coerce").astype("Int64")
    riders["Active"] = riders["Active"].fillna(True).astype(bool)
    return riders.reset_index(drop=True)


def validate_rider_draft(rider_df: pd.DataFrame) -> RiderValidationResult:
    riders = normalise_riders(rider_df)
    errors: list[str] = []
    active = riders[riders["Active"]]
    blank_names = active["Rider Name"].eq("")
    if blank_names.any():
        errors.append("Every active rider needs a Rider Name.")
    blank_starts = active["Start Location"].eq("")
    if blank_starts.any():
        errors.append("Every active rider needs a Start Location.")
    duplicate_names = active["Rider Name"].str.casefold().loc[lambda values: values.ne("")].duplicated(keep=False)
    if duplicate_names.any():
        errors.append("Active rider names must be unique.")
    invalid_max = active["Maximum Jobs"].notna() & active["Maximum Jobs"].le(0)
    if invalid_max.any():
        errors.append("Maximum Jobs must be blank or at least 1.")
    if active.empty:
        errors.append("At least one rider must be active.")
    return RiderValidationResult(not errors, tuple(errors))


def riders_for_optimizer(rider_df: pd.DataFrame) -> pd.DataFrame:
    validation = validate_rider_draft(rider_df)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    riders = normalise_riders(rider_df)
    riders = riders[riders["Active"]].copy()
    riders = riders.rename(columns={"Maximum Jobs": "Max Jobs"})
    return riders[["Rider Name", "Start Location", "Start Zone", "Max Jobs", "Rider Load"]].reset_index(drop=True)


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
    normalised = normalise_riders(draft)
    validation = validate_rider_draft(normalised)
    if not validation.is_valid:
        raise ValueError("; ".join(validation.errors))
    before = normalise_riders(state.get("committed_riders"))
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
    normalised = normalised.reindex(sorted(normalised.columns), axis=1).fillna("")
    payload = normalised.astype(str).to_dict("records")
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
