---
title: BlueSG deployment, security, and operations
tags: [bluesg, deployment, cloud, security]
---

# BlueSG deployment, security, and operations

Back to [[00 BlueSG Index]].

Atomic Cloud web: [[Route Optimiser Web/80 BlueSG Cloud Entry]] → [[Route Optimiser Web/81 Access Gate]] → [[Route Optimiser Web/82 Deployment Preflight]].

## Entrypoints

| Deployment | Entrypoint | Scope |
|---|---|---|
| Full AMS workspace | `app.py` | Home, Lance, Flexar, Contracts, HR |
| BlueSG-only | `Flexar/BlueSG/streamlit_app.py` | optimizer and planner only |

The dedicated entrypoint inserts the repository root into `sys.path`, then calls the shared Cloud router. Do not deploy `Home.py` as an entrypoint.

## BlueSG Cloud configuration

- Main file: `Flexar/BlueSG/streamlit_app.py`.
- Documented Python: 3.12.
- Exact dependency pins:

```text
streamlit==1.57.0
pandas==3.0.3
openpyxl==3.1.5
pydeck==0.9.2
```

- Router paths: `/optimise` (default) and `/review`.
- Deployment guard label: `2026.08.03.1` plus runtime Python major/minor.

## Access control

`cloud_access_control.py` reads secrets from environment first, then Streamlit secrets.

- On Linux, login is required by default.
- On Windows, login is optional unless `APP_PASSWORD` exists or `BLUESG_REQUIRE_LOGIN` enables it.
- False override values are `0`, `false`, `no`, and `off`.
- Successful authentication is kept in `bluesg_cloud_user_authenticated` session state.
- Password comparison uses `hmac.compare_digest`.
- Sign out clears the session flag and reruns.
- If login is required but no `APP_PASSWORD` exists, deployment stops locked.

This is a shared-password gate, not user identity, authorization roles, or an audit trail.

## Required hosted secrets

Variable names only:

```text
APP_PASSWORD
ONEMAP_EMAIL
ONEMAP_PASSWORD
```

Never commit `.env` or a real `.streamlit/secrets.toml`. Do not store a persistent OneMap token in source.

## Deployment preflight

Before page navigation, the router imports:

- pandas, openpyxl, pydeck;
- optimizer config;
- workflow state;
- V2 optimizer;
- V2 daily roster source.

It also verifies named exports. If hot deployment leaves a stale module missing exports, preflight invalidates caches and reloads once. Remaining failures show sanitized module/error categories in the UI; the original traceback is logged server-side.

## Temporary/shared Cloud storage

Cloud filesystem writes may disappear after reboot, redeploy, inactivity shutdown, or instance replacement. Multiple user sessions may share one running instance.

Consequences:

- download every completed workbook that matters;
- keep the approved roster in a separate controlled system of record;
- never rely on Cloud-local cache, roster edits, or run JSON for durability;
- never use the Cloud filesystem as confidential-record storage;
- expect the first route run after cache loss to be slower.

## Privacy warning inherited from the deployment runbook

The source deployment document warns that the repository/history contained staff and candidate personal information and should not be publicly deployed with real data. External repository visibility was not independently verified during this snapshot. Before deployment:

1. verify repository and app access are restricted appropriately;
2. audit current files and Git history for PII/secrets;
3. remove/rewrite exposed history or move to a private controlled repository;
4. use sanitized seed/test inputs only until that review is complete.

A private Streamlit app does not protect files left in a public repository.

## Local smoke check

```powershell
python --version
python -m pip install -r Flexar/BlueSG/requirements.txt
python -m streamlit run Flexar/BlueSG/streamlit_app.py
```

Verify login, both pages, roster aliases/strict fields, small complete optimization, map/planner, workbook download, and absence of traceback in terminal/browser.

## Security review item from this snapshot

A real ignored local Streamlit secrets file exists. No values are reproduced here. Confirm filesystem access, verify it is ignored, and rotate any value exposed to an untrusted transcript/screenshot/service.

## Deployment-sensitive changes

- New import: add its package to the exact Cloud pins and its module/export to preflight when startup-critical.
- New persistent state: Cloud filesystem is not sufficient; introduce an approved external store deliberately.
- Authentication change: distinguish authentication, authorization, tenancy, and audit requirements.
- Page path/name change: update root navigation, Cloud router, Home, deployment tests, and docs together.
