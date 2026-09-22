"""Web application layer for the IFC auditor.

The audit engine (`ifcaudit`) knows nothing about HTTP. This package adds
upload, an async job pipeline, the SQLite query layer and the browser UI on
top of it.
"""

__version__ = "0.2.0"
