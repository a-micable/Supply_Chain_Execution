"""Wrapper FastAPI app entrypoint.

This repo currently hosts the implementation under `src/nexusops`.
The wrapper exists only to match the expected repository layout:
`backend/app/...`.
"""

from nexusops.main import app  # re-export

__all__ = ["app"]

