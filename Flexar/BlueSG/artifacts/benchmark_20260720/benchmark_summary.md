# BlueSG Optimiser Benchmark

Input: `Antares x Flexar - RB Jobs (5) 1.xlsx` (`a83a92bef07b192401ed314c2fcde682ead5db9359cf9f09c9c5870f2c5e9285`)
Selected date: 2026-07-17
Window: 2026-07-17T23:00:00+08:00 to 2026-07-18T03:00:00+08:00
Travel mode: public_transport; OneMap enabled: False

| Algorithm | Assigned | Unassigned | Max duty min | Empty min | Fallback legs | Hard violations | Seconds | Accepted moves |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline_greedy_insertion | 23 | 7 | 216.0 | 519.0 | 46 | 0 | 0.626 | 0 |
| baseline_plus_local_search | 23 | 7 | 216.0 | 519.0 | 46 | 0 | 0.67 | 0 |
| cluster_hint_greedy | 22 | 8 | 224.0 | 514.5 | 44 | 0 | 0.572 | 0 |

## Promotion assessment

The state-aware greedy/insertion solver remains the production default. Local improvement is eligible for promotion only after representative multi-date benchmarks meet every promotion rule; this single-date run is evidence, not automatic promotion.

Baseline assigned 23 job(s) with 0 hard violation(s).
