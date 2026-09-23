# Decisions

- **D001:** Keep strict, provisional, and synthetic statuses separate.
- **D002:** Forecast and availability timestamps are timezone-aware UTC values.
- **D003:** Replay receives an injected `ReplayClock`; it cannot use wall-clock time.
- **D004:** Forecast intervals are left-closed/right-open and `lead_end_hours` starts at one.
- **D005:** Strict access fails closed while the time contract is unresolved.
