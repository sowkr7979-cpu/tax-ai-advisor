"""src/ai/docx_client.py — DOCX review-package writer (docs/03 OUT-002/006).

The 11-목차 review package is deterministic content (built in src/); this adapter
only renders it to .docx. python-docx is an optional dependency.
"""

from __future__ import annotations

from .base import AdapterConfigError


class DocxClient:
    """# TODO(OUT-006): wire python-docx to render the 11-목차 review package
    # (internal vs client copy per OUT-004). Not used by slice ⑥.
    """

    def render(self, sections: dict, out_path: str) -> str:  # pragma: no cover - real wiring
        try:
            import docx  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise AdapterConfigError(
                "python-docx not installed (pip install 'tiw[adapters]')."
            ) from exc
        raise AdapterConfigError("DocxClient render not yet implemented (OUT-006 TODO).")
