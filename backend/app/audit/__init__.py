"""Audit-event emitter (Community-visible interface).

Other parts of the backend call `await emit(event_type, ...)` to announce
something audit-relevant. By default this is a no-op — only the
ee.audit module (Pro / Enterprise) subscribes a real writer.

Failure inside the subscriber MUST NOT break the main code path; we
swallow all exceptions, log them at warning level, and move on. Audit
is observability, not a critical path.
"""

from app.audit.hook import emit, set_subscriber

__all__ = ["emit", "set_subscriber"]
