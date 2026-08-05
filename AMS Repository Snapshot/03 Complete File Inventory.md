---
title: Complete repository file inventory
snapshot_date: 2026-08-05
tracked_file_count: 201
tags: [ams, inventory]
---

# Complete repository file inventory

Back to [[00 Repository Index]].

This is the exact tracked-file inventory at commit `8b82a5f`, grouped by responsibility. Package-marker `__init__.py` files establish importable Python namespaces. Tests and fixtures are source contracts, not generated artifacts.

## Root and workspace configuration plus workspace tests — 22 files

```text
.gitignore
.streamlit/secrets.toml.example
.vscode/settings.json
app.py
benchmark_optimizer.py
CHANGELOG_BLUESG_OPTIMISER.md
Home.py
pytest.ini
README.md
requirements.txt
START AMS WHATSAPP SYSTEM.bat
STOP AMS WHATSAPP SYSTEM.bat
tests/test_bluesg_streamlit_cloud_deployment.py
tests/test_cfs_bulk_pdf.py
tests/test_cfs_generator.py
tests/test_cfs_page_dates.py
tests/test_pdf_utils.py
tests/test_priority_and_geocode_cache.py
tests/test_route_optimiser_terminal.py
tests/test_route_planner.py
tests/test_route_planner_layout.py
tests/test_selective_reshuffle.py
```

The code block combines 12 root/configuration files with the ten workspace-level tests. `Flexar/__init__.py` is listed with BlueSG below.

## Contracts — 16 files

```text
Contracts/__init__.py
Contracts/generators/__init__.py
Contracts/generators/cfs_generator.py
Contracts/generators/loa_generator.py
Contracts/generators/service_agreement_generator.py
Contracts/pages/__init__.py
Contracts/pages/CFS_Generator.py
Contracts/pages/LOA_Generator.py
Contracts/pages/Service_Agreement_Generator.py
Contracts/shared/__init__.py
Contracts/shared/batch_utils.py
Contracts/shared/file_utils.py
Contracts/shared/pdf_utils.py
Contracts/templates/CFS/AMS - CFS - REB - Template.docx
Contracts/templates/LOA/gbh_loa_template.docx
Contracts/templates/Service_Agreement/permanent_placement_service_agreement_template.docx
```

See [[Subsystems/Contracts]].

## Flexar/BlueSG plus Flexar package marker — 46 files

```text
Flexar/__init__.py
Flexar/BlueSG/__init__.py
Flexar/BlueSG/build_optimised_vehicle_routes.py
Flexar/BlueSG/cloud_access_control.py
Flexar/BlueSG/cloud_deployment_preflight.py
Flexar/BlueSG/cloud_streamlit_router.py
Flexar/BlueSG/components/__init__.py
Flexar/BlueSG/components/drag_and_drop_route_assignment_board/index.html
Flexar/BlueSG/components/register_drag_and_drop_route_assignment_board.py
Flexar/BlueSG/convert_results_to_output_safe_values.py
Flexar/BlueSG/data/cache/seed/verified_onemap_address_coordinates_seed.csv
Flexar/BlueSG/improve_routes_after_initial_optimisation.py
Flexar/BlueSG/job_import_staging.py
Flexar/BlueSG/manual_route_assignment_editing_and_recalculation.py
Flexar/BlueSG/Notes/BLUESG_APPLICATION_ROUTES_AND_FILE_RESPONSIBILITIES.md
Flexar/BlueSG/Notes/BLUESG_ROUTE_OPTIMISATION_END_TO_END_WORKFLOW.md
Flexar/BlueSG/optimiser_config.py
Flexar/BlueSG/optimiser_workflow_state.py
Flexar/BlueSG/pages/__init__.py
Flexar/BlueSG/pages/create_optimised_vehicle_routes_page.py
Flexar/BlueSG/pages/review_map_and_manually_adjust_route_assignments_page.py
Flexar/BlueSG/regional_capacity_and_cross_region_assignment_rules.py
Flexar/BlueSG/requirements.txt
Flexar/BlueSG/route_operation_time_window_settings.py
Flexar/BlueSG/route_optimisation_metrics_and_run_summary.py
Flexar/BlueSG/route_optimisation_result_models.py
Flexar/BlueSG/streamlit_app.py
Flexar/BlueSG/STREAMLIT_COMMUNITY_CLOUD_DEPLOYMENT.md
Flexar/BlueSG/tests/conftest.py
Flexar/BlueSG/tests/test_job_workbook_to_optimised_route_export_workflow.py
Flexar/BlueSG/tests/test_output_safe_value_conversion.py
Flexar/BlueSG/tests/test_post_optimisation_route_improvement_safety.py
Flexar/BlueSG/tests/test_regional_capacity_and_cross_region_assignment_rules.py
Flexar/BlueSG/tests/test_route_assignment_hard_constraint_validation.py
Flexar/BlueSG/tests/test_route_operation_windows_and_duty_time.py
Flexar/BlueSG/tests/test_route_optimisation_objective_priority_order.py
Flexar/BlueSG/tests/test_travel_cache_keys_and_route_confidence.py
Flexar/BlueSG/tests/test_vehicle_route_optimiser_v2_core.py
Flexar/BlueSG/tests/test_vehicle_route_optimiser_v2_workflow.py
Flexar/BlueSG/tests/test_zone_adjacency_route_assignments.py
Flexar/BlueSG/tools/__init__.py
Flexar/BlueSG/tools/compare_route_optimisation_algorithms.py
Flexar/BlueSG/travel_cache_keys_and_route_confidence.py
Flexar/BlueSG/v2_daily_roster_source.py
Flexar/BlueSG/validate_route_assignment_hard_constraints.py
Flexar/BlueSG/vehicle_route_optimiser_v2.py
```

The count above includes the shared `Flexar/__init__.py`; BlueSG itself has 45 tracked files. See [[BlueSG/00 BlueSG Index]] for per-file responsibilities.

## Flexar WhatsApp request processor — 45 files

```text
Flexar/whatsapp_request_processor/.env.example
Flexar/whatsapp_request_processor/.gitignore
Flexar/whatsapp_request_processor/__init__.py
Flexar/whatsapp_request_processor/api.py
Flexar/whatsapp_request_processor/app.py
Flexar/whatsapp_request_processor/config.py
Flexar/whatsapp_request_processor/data/.gitkeep
Flexar/whatsapp_request_processor/database.py
Flexar/whatsapp_request_processor/location_parser.py
Flexar/whatsapp_request_processor/migrations.py
Flexar/whatsapp_request_processor/models.py
Flexar/whatsapp_request_processor/outbound_service.py
Flexar/whatsapp_request_processor/payload_parser.py
Flexar/whatsapp_request_processor/README.md
Flexar/whatsapp_request_processor/request_engine.py
Flexar/whatsapp_request_processor/request_policy.py
Flexar/whatsapp_request_processor/requirements.txt
Flexar/whatsapp_request_processor/reset_test_data.bat
Flexar/whatsapp_request_processor/run_tests.bat
Flexar/whatsapp_request_processor/runtime_support.py
Flexar/whatsapp_request_processor/scripts/ams_supervisor.py
Flexar/whatsapp_request_processor/scripts/start_ams_whatsapp.ps1
Flexar/whatsapp_request_processor/scripts/stop_ams_whatsapp.ps1
Flexar/whatsapp_request_processor/simulator_service.py
Flexar/whatsapp_request_processor/start_local.bat
Flexar/whatsapp_request_processor/test_payloads.py
Flexar/whatsapp_request_processor/tests/conftest.py
Flexar/whatsapp_request_processor/tests/test_api.py
Flexar/whatsapp_request_processor/tests/test_inactivity.py
Flexar/whatsapp_request_processor/tests/test_live_architecture.py
Flexar/whatsapp_request_processor/tests/test_matching.py
Flexar/whatsapp_request_processor/tests/test_outbound.py
Flexar/whatsapp_request_processor/tests/test_payload_builders.py
Flexar/whatsapp_request_processor/tests/test_payload_parser.py
Flexar/whatsapp_request_processor/tests/test_request_engine.py
Flexar/whatsapp_request_processor/tests/test_request_sessions.py
Flexar/whatsapp_request_processor/tests/test_runtime_support.py
Flexar/whatsapp_request_processor/tests/test_streamlit_app.py
Flexar/whatsapp_request_processor/tests/test_supervisor_safety.py
Flexar/whatsapp_request_processor/tests/test_validation_engine.py
Flexar/whatsapp_request_processor/tests/test_waapi_safety.py
Flexar/whatsapp_request_processor/ui_components.py
Flexar/whatsapp_request_processor/validation_engine.py
Flexar/whatsapp_request_processor/waapi_client.py
Flexar/whatsapp_request_processor/worker.py
```

See [[Subsystems/Flexar WhatsApp Request Processor]].

## HR — 8 files

```text
HR/__init__.py
HR/RDL/__init__.py
HR/RDL/app.py
HR/RDL/rdl_editor.py
HR/RDL/rdl_parser.py
HR/RDL/rdl_storage.py
HR/RDL_Archives/HRIQ_RDL_20260714_171111.zip
HR/RDL_Archives/HRIQ_RDL_20260714_171111.zip.sha256
```

See [[Subsystems/HR and HRIQ]].

## Lance — 64 files

```text
Lance/__init__.py
Lance/Converter/__init__.py
Lance/Converter/Converter.py
Lance/HRIQ_Report_Tool/.env.example
Lance/HRIQ_Report_Tool/.gitignore
Lance/HRIQ_Report_Tool/__init__.py
Lance/HRIQ_Report_Tool/app.py
Lance/HRIQ_Report_Tool/config/__init__.py
Lance/HRIQ_Report_Tool/config/settings.py
Lance/HRIQ_Report_Tool/parser/__init__.py
Lance/HRIQ_Report_Tool/parser/batch_parser.py
Lance/HRIQ_Report_Tool/parser/rdl_parser.py
Lance/HRIQ_Report_Tool/parser/sources.py
Lance/HRIQ_Report_Tool/query_engine/__init__.py
Lance/HRIQ_Report_Tool/query_engine/connection.py
Lance/HRIQ_Report_Tool/query_engine/executor.py
Lance/HRIQ_Report_Tool/query_engine/safety.py
Lance/HRIQ_Report_Tool/README.md
Lance/HRIQ_Report_Tool/scraper/__init__.py
Lance/HRIQ_Report_Tool/scraper/auth.py
Lance/HRIQ_Report_Tool/scraper/browser.py
Lance/HRIQ_Report_Tool/scraper/crawler.py
Lance/HRIQ_Report_Tool/scraper/downloader.py
Lance/HRIQ_Report_Tool/scraper/models.py
Lance/HRIQ_Report_Tool/scraper/selectors.py
Lance/HRIQ_Report_Tool/scraper/ssrs_client.py
Lance/HRIQ_Report_Tool/services/__init__.py
Lance/HRIQ_Report_Tool/services/archive_service.py
Lance/HRIQ_Report_Tool/services/cache_service.py
Lance/HRIQ_Report_Tool/services/crawl_state.py
Lance/HRIQ_Report_Tool/services/job_manager.py
Lance/HRIQ_Report_Tool/services/log_service.py
Lance/HRIQ_Report_Tool/services/report_library.py
Lance/HRIQ_Report_Tool/tests/__init__.py
Lance/HRIQ_Report_Tool/tests/conftest.py
Lance/HRIQ_Report_Tool/tests/fixtures/ssrs_catalog_response.json
Lance/HRIQ_Report_Tool/tests/fixtures/ssrs_folder_page.html
Lance/HRIQ_Report_Tool/tests/fixtures/ssrs_nested_folder_page.html
Lance/HRIQ_Report_Tool/tests/test_archive_and_zip_sources.py
Lance/HRIQ_Report_Tool/tests/test_incremental_index.py
Lance/HRIQ_Report_Tool/tests/test_rdl_parser.py
Lance/HRIQ_Report_Tool/tests/test_resume_state.py
Lance/HRIQ_Report_Tool/tests/test_sql_safety.py
Lance/HRIQ_Report_Tool/tests/test_ssrs_client.py
Lance/HRIQ_Report_Tool/tests/test_ssrs_structure.py
Lance/HRIQ_Report_Tool/ui/__init__.py
Lance/HRIQ_Report_Tool/ui/components.py
Lance/HRIQ_Report_Tool/ui/download_page.py
Lance/HRIQ_Report_Tool/ui/reports_page.py
Lance/HRIQ_Report_Tool/ui/sql_page.py
Lance/Recruitment_Tracker.py
Lance/Sesami/__init__.py
Lance/Sesami/Sesami.py
Lance/Sesami/SesamiProcess.py
Lance/Sesami/SesamiScrape.py
Lance/Tender/__init__.py
Lance/Tender/Tender.py
Lance/Tender/TenderProcess.py
Lance/Tender/TenderScrape.py
Lance/whatsapp/__init__.py
Lance/whatsapp/WhatsApp.py
Lance/whatsapp/whatsapp_driver.py
Lance/whatsapp/whatsapp_monitor.py
Lance/whatsapp/whatsapp_storage.py
```

See [[Subsystems/Lance Tools]] and [[Subsystems/HR and HRIQ]].

## Present but intentionally not enumerated file-by-file

These paths were present locally but are not part of the 201-file tracked source inventory:

- `.obsidian/`: Obsidian configuration plus this knowledge base.
- `.env` and `.streamlit/secrets.toml`: ignored sensitive configuration; values excluded.
- `.venv/`: installed Python environment; reproducible from dependency files.
- `.git/`: version-control database.
- `.pytest_cache/` and `**/__pycache__/`: disposable caches.
- `runs/`: 14 generated BlueSG JSON run summaries at snapshot time.
- `Flexar/BlueSG/data/cache/runtime/`: two generated OneMap caches.
- tool-specific databases, logs, runtime state, downloads, and user uploads ignored by `.gitignore`.

These exclusions prevent this note from becoming a secret dump or a duplicate of rebuildable/generated data while still recording that each category exists.
