---
title: BlueSG access gate
tags: [bluesg, route-optimiser, security, authentication]
---

# Access gate

Parent: [[80 BlueSG Cloud Entry]]. Provider secret edge: [[51 OneMap Credential and Token Flow]].

`require_cloud_access` reads environment before Streamlit secrets.

## Policy

- Linux: login required by default;
- Windows: optional unless configured;
- `BLUESG_REQUIRE_LOGIN` can override;
- missing required `APP_PASSWORD` locks deployment;
- password comparison uses `hmac.compare_digest`;
- successful state is per Streamlit session;
- sign out clears it and reruns.

## Boundary

This is a shared-password authentication gate. It is not individual identity, role authorization, tenancy isolation, or durable audit.

## Secret rule

Never copy `APP_PASSWORD`, OneMap credentials, or session values into [[63 Canonical Metrics and Run Artifact]] or Graph notes.

