"""Production-path benchmark for the BlueSG baseline and bounded local search."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, time as clock_time
from pathlib import Path
from typing import Any

import pandas as pd

from Flexar.BlueSG.operation_context import OperationContext
from Flexar.BlueSG.output_sanitizer import sanitize_for_output
from Flexar.BlueSG.run_metrics import create_run_result, sha256_bytes
from Flexar.BlueSG.vehicle_route_optimizer import (
    build_unassigned_jobs_df,
    export_routes_to_excel,
    improve_route_dataframe,
    load_and_validate_jobs,
    load_rider_roster,
    optimisation_integrity_report,
    optimise_vehicle_routes,
    validate_riders,
)


LOGGER = logging.getLogger("bluesg.benchmark")
DEFAULT_ALGORITHMS = ["baseline_greedy_insertion", "baseline_plus_local_search"]


def _parse_clock(value: str) -> clock_time:
    return clock_time.fromisoformat(value)


def _load_selected_jobs(input_path: Path, selected_date: date) -> tuple[pd.DataFrame, int, list[str]]:
    with input_path.open("rb") as stream:
        jobs, missing, warnings = load_and_validate_jobs(stream)
    if missing:
        raise ValueError("Missing required job headers: " + ", ".join(missing))
    uploaded_count = len(jobs)
    dates = pd.to_datetime(jobs.get("Date"), errors="coerce").dt.date
    selected = jobs.loc[dates == selected_date].copy()
    selected.attrs.update(jobs.attrs)
    selected.attrs["uploaded_count"] = uploaded_count
    if selected.empty:
        raise ValueError(f"No valid jobs found for {selected_date}.")
    return selected, uploaded_count, warnings


def _run_algorithm(
    algorithm: str,
    jobs: pd.DataFrame,
    riders: list[Any],
    context: OperationContext,
    settings: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], list[dict[str, Any]], float]:
    started = time.perf_counter()
    route_df, summary_df, warnings = optimise_vehicle_routes(
        jobs,
        riders,
        use_onemap=bool(settings["use_onemap"]),
        optimise_by="duration",
        operation_context=context,
        fallback_penalty=float(settings["fallback_penalty"]),
        cluster_pressure_bonus_per_job=(
            float(settings["cluster_pressure_bonus_per_job"])
            if algorithm == "cluster_hint_greedy"
            else 0.0
        ),
        experimental_cluster_first=algorithm == "cluster_first_experimental",
        max_total_duty_time_min=settings.get("max_total_duty_time_min"),
        regional_overflow_config=settings.get("regional_overflow_config"),
    )
    audit: list[dict[str, Any]] = []
    if algorithm == "baseline_plus_local_search":
        route_df, summary_df, local_warnings, audit = improve_route_dataframe(
            route_df,
            jobs,
            riders,
            context,
            settings,
            [],
            time_limit_seconds=int(settings["local_search_time_limit_seconds"]),
            max_iterations=int(settings["local_search_max_iterations"]),
        )
        warnings = sorted(set([*warnings, *local_warnings]))
    return route_df, summary_df, warnings, audit, time.perf_counter() - started


def run_benchmark(args: argparse.Namespace) -> list[dict[str, Any]]:
    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    outputs_dir = output_dir / "outputs"
    runs_dir = output_dir / "runs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    runs_dir.mkdir(parents=True, exist_ok=True)
    selected_date = date.fromisoformat(args.date)
    jobs, uploaded_count, parser_warnings = _load_selected_jobs(input_path, selected_date)
    roster = load_rider_roster(selected_date.strftime("%A"), Path(args.rider_roster) if args.rider_roster else None) if args.rider_roster else load_rider_roster(selected_date.strftime("%A"))
    original_riders, rider_errors = validate_riders(roster)
    if rider_errors:
        raise ValueError("; ".join(rider_errors))
    context = OperationContext.for_window(
        selected_date,
        _parse_clock(args.start),
        _parse_clock(args.end),
        empty_travel_mode=args.empty_travel_mode,
        pickup_handling_min=args.pickup_handling_min,
        dropoff_handling_min=args.dropoff_handling_min,
        unlock_wait_min=args.unlock_wait_min,
        default_operational_buffer_pct=args.operational_buffer_pct / 100.0,
    )
    base_settings = {
        "jobs_uploaded": uploaded_count,
        "use_onemap": bool(args.use_onemap),
        "fallback_penalty": args.fallback_penalty,
        "cluster_pressure_bonus_per_job": args.cluster_hint,
        "local_search_time_limit_seconds": args.local_search_seconds,
        "local_search_max_iterations": args.local_search_iterations,
        "max_total_duty_time_min": args.max_total_duty_min,
        "operation_context": context.to_settings(),
        "constraints": [],
        "regional_overflow_config": {
            "enabled": not args.disable_regional_overflow,
            "support_tolerance_min": args.support_tolerance_min,
            "support_tolerance_ratio": args.support_tolerance_ratio,
            "protected_job_advantage_min": args.protected_job_advantage_min,
            "approved_support_penalty": args.approved_support_penalty,
            "unsupported_region_penalty": args.unsupported_region_penalty,
            "clustered_trip_penalty": 0.0,
            "clustered_trip_min_jobs": 3,
            "scarce_driver_small_escape_penalty": args.scarce_driver_small_escape_penalty,
            "scarce_driver_large_escape_penalty": args.scarce_driver_large_escape_penalty,
        },
    }
    input_hash = sha256_bytes(input_path.read_bytes())
    results = []
    for algorithm in args.algorithms:
        LOGGER.info("Starting %s on %s selected jobs", algorithm, len(jobs))
        # Optimisation mutates operational rider state; every algorithm gets a fresh parse.
        riders, _ = validate_riders(roster.copy())
        route_df, summary_df, warnings, audit, elapsed = _run_algorithm(
            algorithm, jobs.copy(), riders, context, base_settings
        )
        integrity = optimisation_integrity_report(route_df, jobs)
        validation = {key: value for key, value in integrity.items() if key != "unassigned_df"}
        validation.update(route_df.attrs.get("hard_constraint_validation", {}))
        run_result = create_run_result(
            route_df=route_df,
            unassigned_df=build_unassigned_jobs_df(jobs, route_df),
            riders=riders,
            context=context,
            settings={**base_settings, "wall_clock_seconds": elapsed},
            input_filename=input_path.name,
            input_sha256=input_hash,
            selected_job_date=str(selected_date),
            warnings=[
                {
                    "severity": "manual_review" if "fallback" in warning.casefold() or "low-confidence" in warning.casefold() else "warning",
                    "message": warning,
                }
                for warning in [*parser_warnings, *warnings]
            ],
            move_audit=audit,
            validation=validation,
            algorithm_name=algorithm,
        )
        (outputs_dir / f"{algorithm}.xlsx").write_bytes(
            export_routes_to_excel(
                route_df,
                summary_df,
                jobs_df=jobs,
                lookup_warnings=warnings,
                run_result=run_result,
                move_audit=audit,
            )
        )
        (runs_dir / f"{algorithm}_run_summary.json").write_text(
            json.dumps(sanitize_for_output(run_result.summary), indent=2, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        row = {"algorithm": algorithm, **run_result.summary}
        row.pop("settings", None)
        row.pop("manual_feedback", None)
        row["objective_tuple"] = json.dumps(row.get("objective_tuple", []))
        results.append(sanitize_for_output(row))
        LOGGER.info("Finished %s: assigned=%s max-duty=%s", algorithm, row["jobs_assigned"], row["longest_rider_duty_min"])

    pd.DataFrame(results).to_csv(output_dir / "benchmark_results.csv", index=False)
    (output_dir / "benchmark_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    baseline = next((row for row in results if row["algorithm"] == "baseline_greedy_insertion"), results[0])
    markdown = [
        "# BlueSG Optimiser Benchmark",
        "",
        f"Input: `{input_path.name}` (`{input_hash}`)",
        f"Selected date: {selected_date}",
        f"Window: {context.operation_start.isoformat()} to {context.operation_end.isoformat()}",
        f"Travel mode: {context.empty_travel_mode}; OneMap enabled: {args.use_onemap}",
        "",
        "| Algorithm | Assigned | Unassigned | Max duty min | Empty min | Fallback legs | Hard violations | Seconds | Accepted moves |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in results:
        markdown.append(
            f"| {row['algorithm']} | {row['jobs_assigned']} | {row['jobs_unassigned']} | "
            f"{row['longest_rider_duty_min']} | {row['total_empty_travel_min']} | "
            f"{row['fallback_leg_count']} | {row['hard_violation_count']} | "
            f"{row['wall_clock_seconds']} | {row['accepted_local_search_moves']} |"
        )
    markdown.extend(
        [
            "",
            "## Promotion assessment",
            "",
            "The state-aware greedy/insertion solver remains the production default. Local improvement is eligible for promotion only after representative multi-date benchmarks meet every promotion rule; this single-date run is evidence, not automatic promotion.",
            "",
            f"Baseline assigned {baseline['jobs_assigned']} job(s) with {baseline['hard_violation_count']} hard violation(s).",
        ]
    )
    (output_dir / "benchmark_summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--algorithms", nargs="+", default=DEFAULT_ALGORITHMS)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rider-roster")
    parser.add_argument("--start", default="14:00")
    parser.add_argument("--end", default="17:00")
    parser.add_argument("--empty-travel-mode", default="public_transport")
    parser.add_argument("--pickup-handling-min", type=float, default=3.0)
    parser.add_argument("--dropoff-handling-min", type=float, default=3.0)
    parser.add_argument("--unlock-wait-min", type=float, default=0.0)
    parser.add_argument("--operational-buffer-pct", type=float, default=20.0)
    parser.add_argument("--fallback-penalty", type=float, default=100.0)
    parser.add_argument("--cluster-hint", type=float, default=30.0)
    parser.add_argument("--max-total-duty-min", type=float)
    parser.add_argument("--local-search-seconds", type=int, default=30)
    parser.add_argument("--local-search-iterations", type=int, default=100)
    parser.add_argument("--use-onemap", action="store_true")
    parser.add_argument("--disable-regional-overflow", action="store_true")
    parser.add_argument("--support-tolerance-min", type=float, default=15.0)
    parser.add_argument("--support-tolerance-ratio", type=float, default=1.25)
    parser.add_argument("--protected-job-advantage-min", type=float, default=15.0)
    parser.add_argument("--approved-support-penalty", type=float, default=5.0)
    parser.add_argument("--unsupported-region-penalty", type=float, default=180.0)
    parser.add_argument("--scarce-driver-small-escape-penalty", type=float, default=40.0)
    parser.add_argument("--scarce-driver-large-escape-penalty", type=float, default=180.0)
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_benchmark(build_parser().parse_args())


if __name__ == "__main__":
    main()
