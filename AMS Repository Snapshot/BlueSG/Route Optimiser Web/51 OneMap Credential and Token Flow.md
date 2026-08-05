---
title: OneMap credential and token flow
tags: [bluesg, route-optimiser, onemap, security]
---

# OneMap credential and token flow

Provider parent: [[50 V1 Compatibility Surface]]. Consumers: [[52 Geocode Resolution]] and [[41 Travel Matrix Construction]].

Credential/token sources include manual session token, environment/root `.env`, Streamlit secrets, and OneMap email/password used to request a fresh token.

## Lifecycle

- load configured value without exposing it to a widget;
- parse token expiry;
- reuse a valid active token;
- refresh when forced/expired;
- retain active token in session state only.

## Security invariants

- no credential/token in run settings, workbook, notes, or visible prefilled widgets;
- sanitized deployment failures through [[82 Deployment Preflight]];
- secret locations governed by [[81 Access Gate]] and Cloud configuration.

## Downstream

Authenticated requests populate [[52 Geocode Resolution]] and [[53 Travel Route Cache Identity]]. Failure may trigger [[54 Fallback and Confidence]].

