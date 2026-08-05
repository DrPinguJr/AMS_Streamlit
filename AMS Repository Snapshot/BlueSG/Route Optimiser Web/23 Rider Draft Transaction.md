---
title: Rider draft transaction
tags: [bluesg, route-optimiser, roster, streamlit-state]
---

# Rider draft transaction

Upstream: [[22 Daily Roster Sources]]. Downstream: [[24 V2 Rider Validation]] and [[21 Result Staleness Signature]].

The “Today's riders” dialog begins from normalized committed riders. Cancel discards the draft. Save reconciles new `Maximum` and compatibility `Maximum Jobs`, validates, then atomically replaces committed riders.

## Draft columns

Rider Name, Start Location, Start Zone, Preferred, Maximum, Work Style, End Requirement, Active, plus compatibility Maximum Jobs and Rider Load.

## State effects

- unchanged save: committed data remains equivalent;
- changed save with no result: no stale result exists;
- changed save with a result: marks result stale;
- invalid save: committed roster is untouched.

## Connections

Work-style meaning → [[25 Work Styles and Area Lead]]. End requirement → [[26 End Requirements and Availability]].

