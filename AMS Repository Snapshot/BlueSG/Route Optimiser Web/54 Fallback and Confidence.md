---
title: Travel fallback and confidence
tags: [bluesg, route-optimiser, travel-quality]
---

# Fallback and confidence

Triggered when [[51 OneMap Credential and Token Flow]], [[52 Geocode Resolution]], or live routing cannot provide verified travel.

## Confidence mapping

- manual source → manual;
- fallback/estimate → fallback;
- cache → cached_verified;
- otherwise → verified.

Fallback zone estimates can keep a plan operational but must emit a `LOW-CONFIDENCE ROUTE` warning for manual verification.

## Separation of concerns

- estimated duration remains the displayed/feasibility duration;
- fallback quality penalty changes ranking only;
- usable fallback is not counted as a failed route;
- missing duration is unusable and reaches [[44 Hard Feasibility]].

## Output edges

Warnings appear in [[49 V2 Status and Explanations]], [[63 Canonical Metrics and Run Artifact]], and `Manual Review` in [[64 Excel Workbook Contract]].

