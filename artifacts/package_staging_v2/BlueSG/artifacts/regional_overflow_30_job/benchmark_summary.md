# Capacity-Aware Regional Overflow Benchmark

Deterministic anonymised fixture: 30 jobs, including 15 West-related jobs, one West rider, and North/Central/East/North-East riders. Window: 14:00-17:00 Asia/Singapore. Travel provider: deterministic verified fake matrix; no network calls. Fixture SHA-256: `1cc5363d2777d6c12e9b6d75ff83e28be98cc95a9eb3329abda0fdd86523a116`.

| Algorithm | Assigned | Hard violations | Max duty min | Empty travel min | Unsupported exceptions |
|---|---:|---:|---:|---:|---:|
| Unprotected baseline | 30 | 0 | 178.0 | 234.0 | 9 |
| Capacity-aware regional overflow | 30 | 0 | 86.5 | 220.5 | 1 |

The regional policy preserved 30/30 coverage and zero hard violations, reduced maximum duty and total empty travel, and kept unsupported work visible as an exception. This synthetic benchmark verifies behaviour; real-date tuning is still required before changing operational penalty defaults.
