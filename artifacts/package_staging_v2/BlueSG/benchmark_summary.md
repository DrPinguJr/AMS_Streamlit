# BlueSG Optimiser Benchmark

Input: `Antares x Flexar - RB Jobs (5) 1.xlsx` (`a83a92bef07b192401ed314c2fcde682ead5db9359cf9f09c9c5870f2c5e9285`)
Selected date: 2026-07-17
Window: 2026-07-17T23:00:00+08:00 to 2026-07-18T03:00:00+08:00
Travel mode: public_transport; OneMap enabled: False

| Algorithm | Assigned | Unassigned | Max duty min | Empty min | Fallback legs | Hard violations | Seconds | Accepted moves |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_greedy_insertion | 30 | 0 | 224.0 | 621.0 | 60 | 0 | 0.483 | 0 |
| baseline_plus_local_search | 30 | 0 | 224.0 | 666.0 | 60 | 0 | 5.811 | 1 |
| cluster_hint_greedy | 30 | 0 | 224.0 | 619.5 | 60 | 0 | 0.663 | 0 |

## Promotion assessment

The state-aware greedy/insertion solver remains the production default. Local improvement is eligible for promotion only after representative multi-date benchmarks meet every promotion rule; this single-date run is evidence, not automatic promotion.

Baseline assigned 30 job(s) with 0 hard violation(s).
