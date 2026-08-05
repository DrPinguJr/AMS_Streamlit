---
title: AMS repository knowledge base
snapshot_date: 2026-08-05
git_commit: 8b82a5fc9f08a1b0ac2b5eafd7c243d791fe3e5a
branch: main
tags:
  - ams
  - repository-snapshot
  - index
---

# AMS repository knowledge base

This vault section is the one-time technical baseline for `AMS_Streamlit` before the next large change. It describes the repository as it existed on 2026-08-05 at commit `8b82a5f` (`feat: Update deployment documentation and enhance module import checks for BlueSG application`).

The source tree was clean when inspected. `.obsidian/` was the only untracked path, and these notes are the intended new content.

## Start here

- [[01 Snapshot Baseline]] — exact Git, dependency, runtime-artifact, and test baseline.
- [[02 Architecture and Navigation]] — how the grouped Streamlit workspace fits together.
- [[03 Complete File Inventory]] — file-by-file repository inventory and exclusions.
- [[04 Runtime Data Security and Operations]] — mutable data, secrets, external systems, and operating boundaries.
- [[05 Tests and Change Protocol]] — what is protected and how to make the next large change safely.

## Product areas

- [[Subsystems/Contracts]]
- [[Subsystems/Flexar WhatsApp Request Processor]]
- [[Subsystems/HR and HRIQ]]
- [[Subsystems/Lance Tools]]

## BlueSG — primary change area

BlueSG receives the heaviest coverage because it is the expected target of the next large change.

- [[BlueSG/00 BlueSG Index]]
- [[BlueSG/Route Optimiser Web/00 Route Optimiser Mega Web]] — graph-first bridge into the atomic optimizer web.
- [[BlueSG/01 Architecture and Module Map]]
- [[BlueSG/02 Optimiser V2 Deep Dive]]
- [[BlueSG/03 V1 Compatibility Backend]]
- [[BlueSG/04 Data Input State and Schemas]]
- [[BlueSG/05 Route Planner Deep Dive]]
- [[BlueSG/06 Travel OneMap Cache and Confidence]]
- [[BlueSG/07 Outputs Metrics and Artifacts]]
- [[BlueSG/08 Deployment Security Operations]]
- [[BlueSG/09 Tests Guarantees and Known Issues]]
- [[BlueSG/10 Change Impact Playbook]]
- [[BlueSG/11 Glossary and Defaults]]

## Existing source documentation

These source-controlled documents remain authoritative historical or operational references and were not duplicated verbatim:

- `README.md` — workspace setup and app list.
- `CHANGELOG_BLUESG_OPTIMISER.md` — V1/optimizer evolution through the unreleased regional policy changes.
- `Flexar/BlueSG/Notes/BLUESG_APPLICATION_ROUTES_AND_FILE_RESPONSIBILITIES.md` — earlier BlueSG module guide.
- `Flexar/BlueSG/Notes/BLUESG_ROUTE_OPTIMISATION_END_TO_END_WORKFLOW.md` — earlier V1-centered end-to-end workflow.
- `Flexar/BlueSG/STREAMLIT_COMMUNITY_CLOUD_DEPLOYMENT.md` — BlueSG Cloud deployment runbook.
- `Flexar/whatsapp_request_processor/README.md` — local simulation stack and safety model.
- `Lance/HRIQ_Report_Tool/README.md` — HRIQ download, parsing, archive, and SQL workflow.

## Reading convention

- **Current** means directly observed in the code at the snapshot commit.
- **Compatibility** means still required by callers/exports/planner even if a newer implementation is selected.
- **Generated** means runtime output and not a source-of-truth input.
- **Sensitive** means values must not be copied into notes, logs, Git, run summaries, or issue descriptions.
