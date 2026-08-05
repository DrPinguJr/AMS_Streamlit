---
title: BlueSG travel, OneMap, cache, and confidence
tags: [bluesg, onemap, cache, routing]
---

# BlueSG travel, OneMap, cache, and confidence

Back to [[00 BlueSG Index]].

Atomic provider web: [[Route Optimiser Web/51 OneMap Credential and Token Flow]] → [[Route Optimiser Web/52 Geocode Resolution]] → [[Route Optimiser Web/53 Travel Route Cache Identity]] → [[Route Optimiser Web/54 Fallback and Confidence]].

## Provider boundary

OneMap and fallback behavior lives mainly in `build_optimised_vehicle_routes.py`. Both V1 and V2 call that boundary; planner recalculation uses it as well.

Important value objects:

- `GeocodeResult`: address, latitude, longitude, source, warning/error, availability.
- `TravelCost`: distance, duration, source, warning, route path/text, confidence; can convert to canonical leg results.

## Credential/token sources

The UI/backend can use a manual session token, environment variables/root `.env`, or Streamlit secrets/OneMap account credentials to obtain/refresh a token. Active tokens are cached in session state with expiry handling.

Security invariants:

- credential/token widgets must never prefill stored secret values;
- tokens and credentials must not enter run summaries/workbooks/this vault;
- deployment error pages must not echo arbitrary provider exceptions/secrets.

## Geocoding

Unique rider starts, pickups, and drop-offs are deduplicated and can be geocoded concurrently. Lookup order is effectively in-memory → disk seed/runtime cache → OneMap → explicit fallback/unavailable result.

Cache paths:

```text
data/cache/seed/verified_onemap_address_coordinates_seed.csv
data/cache/runtime/onemap_address_coordinates_runtime_cache.csv
data/cache/runtime/onemap_travel_routes_runtime_cache.csv
```

The seed is tracked/read-only. Runtime files are mutable/ignored. Cache I/O uses a lock.

## Contextual travel-cache key

Current key tuple:

```text
normalized origin
normalized destination
normalized travel mode
service day class
time bucket
provider version (`onemap-v1`)
```

For public transport, service day is weekday/weekend and time is a 15-minute operation-start bucket. Non-public-transport routes are currently keyed as `all-days` / `timeless`. This prevents public-transport cache reuse across incompatible departure contexts while permitting broader reuse of driving-like routes.

Any change to provider interpretation or response geometry should bump provider version or migrate/clear runtime caches.

## Empty versus loaded legs

- Empty leg: rider current location to job pickup; uses configured empty travel mode and optional public-transport multiplier/wait buffer.
- Loaded leg: pickup to drop-off while driving the vehicle.
- The previous job’s drop-off becomes the next empty-leg origin.
- V2 precomputes all candidate empty pairs and each loaded job pair before search.
- Planner reuses atomic loaded legs and recalculates changed connectors.

## Fallback semantics

Fallback zone estimates allow an operational result when verified routing is unavailable. They are low confidence and must be visible.

- The fallback quality penalty affects candidate ranking, not the displayed duration.
- A fallback carrying a usable duration is counted as fallback, not provider failure.
- Missing duration is a failed/unusable route.
- Standard warning begins `LOW-CONFIDENCE ROUTE` and directs manual verification before dispatch.

Confidence mapping:

| Source text | Confidence |
|---|---|
| contains `manual` | manual |
| contains `fallback` or `estimate` | fallback |
| contains `cache` | cached_verified |
| otherwise | verified |

## Runtime snapshot

At the snapshot:

- geocode runtime CSV: 3,240 bytes;
- travel route runtime CSV: 50,149,649 bytes.

The large route cache is a performance asset, not a source of truth. Community Cloud may delete it on restart/redeploy.

## Change traps

- Reusing public transport outside its 15-minute/day context.
- Changing mode names without a key migration.
- Treating a cache hit as verified without considering what originally populated it.
- Hiding fallback warnings to make KPIs look cleaner.
- Applying quality penalties to reported operational duration.
- Performing travel I/O inside V2 beam expansion.
- Copying cached addresses/routes into documentation when they may contain live operational data.
