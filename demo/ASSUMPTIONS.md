# ASSUMPTIONS (MVP)

Honest unknowns for the demo package. Do not treat these as jury-confirmed facts.

| Topic | Assumption | Status |
|-------|------------|--------|
| SCADA files | Real XLSX not in repo yet; bundled synthetic fixtures used | provisional |
| Coordinates | `sites.yaml` may have null lat/lon → FixtureProvider weather | provisional |
| Timezone | Naive SCADA timestamps treated as UTC | provisional |
| Interval label | Timestamp = interval start (10-min samples → hourly mean) | provisional |
| Horizon | `rolling_next_48` hourly leads from origin | engineering default |
| February 2026 actuals | Absent in fixtures (and likely in real files ending 2026-01-31) → score `not_evaluated` | confirmed for fixtures |
| Weather source | Open-Meteo forecast API only when coords present; else fixture | MVP |
| Agent | One supervisor + tools; LLM never edits power numbers | design |

Fill real coordinates and drop XLSX into `data/raw/` to move toward a stricter run.
