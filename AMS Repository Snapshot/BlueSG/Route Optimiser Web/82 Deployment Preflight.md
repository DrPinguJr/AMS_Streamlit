---
title: BlueSG deployment preflight
tags: [bluesg, route-optimiser, cloud, preflight]
---

# Deployment preflight

Parent: [[80 BlueSG Cloud Entry]]. Runs after [[81 Access Gate]] and before page navigation.

Preflight imports pandas, openpyxl, pydeck, optimizer config, workflow state, V2 optimizer, and daily roster source. It verifies required named exports.

## Stale-module behavior

If exports are missing after import, it invalidates caches and reloads once. Missing exports after reload fail startup.

## Error safety

- sanitized module/error summary appears in UI;
- full original traceback goes to Cloud logs;
- arbitrary exception content is not displayed publicly.

## Change edge

New startup-critical modules/exports require exact dependency updates and preflight/test changes through [[91 Change Impact Routes]].

## Test edge

Import success, reload, missing dependency, sanitization, pins, and paths are in [[90 Behaviour Contract Map]].

