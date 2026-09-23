# Continue from here

T00 is blocked on the missing XLSX/PDF and inaccessible Maps redirects. The T01 scaffold is in
place, but package-index access failed before `uv.lock` and dependency-backed tests could be
completed. The independent parts of T02 are implemented and pass static/bytecode checks. First
retry `uv lock && uv sync --dev && uv run pytest`; then add T03 read-only Excel auditing and
duration-weighted hourly aggregation against small synthetic fixtures. When the original
workbooks arrive, run the audit without modifying them and record hashes/counts in an input
manifest.
