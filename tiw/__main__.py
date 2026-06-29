"""``python -m tiw`` → orchestrator CLI (``tiw.cli``).

The evaluation harness stays at ``python -m tiw.eval`` (separate entrypoint —
untouched by this CLI)."""

from __future__ import annotations

from tiw.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
