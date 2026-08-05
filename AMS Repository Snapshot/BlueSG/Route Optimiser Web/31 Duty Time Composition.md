---
title: Route duty time composition
tags: [bluesg, route-optimiser, metrics]
---

# Duty time composition

Context: [[30 Operation Context]]. Inputs: [[41 Travel Matrix Construction]]. Output metrics: [[63 Canonical Metrics and Run Artifact]].

For each job:

```text
empty travel + pickup handling + unlock wait + loaded travel + drop-off handling
```

The first empty leg is first positioning. Each later empty leg begins at the prior drop-off. Adjusted duty applies the operational buffer.

## Distinct measures

- empty travel;
- loaded travel;
- route time;
- first positioning;
- total duty;
- adjusted duty;
- final completion ETA.

## Invariant

Do not optimize one duration while displaying another without clear labels. Fallback quality penalties from [[54 Fallback and Confidence]] must not alter reported minutes.

## Constraint edge

Completion after operation/availability/end deadline is evaluated in [[44 Hard Feasibility]].

