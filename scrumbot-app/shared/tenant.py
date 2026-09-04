"""Server-side tenant binding for Strands tools.

Every tool that touches user data takes `user_id` as a parameter, because the
model has to name the user in the tool call. The model learns that id from the
system prompt — which means a hostile SMS can ask the agent to "use user
+1555…" instead. The handler binds the authenticated user for the duration of
the agent turn; tools call `enforce_user()` and act on the bound id no matter
what the model passed.

Outside an agent turn (unit tests, scripts) nothing is bound and the supplied
id passes through unchanged.
"""

from contextlib import contextmanager
from contextvars import ContextVar

from aws_lambda_powertools import Logger

logger = Logger()

_bound_user_id: ContextVar[str | None] = ContextVar("stride_bound_user_id", default=None)


@contextmanager
def bind_user(user_id: str):
    """Bind the authenticated user for the enclosed agent turn."""
    token = _bound_user_id.set(user_id)
    try:
        yield
    finally:
        _bound_user_id.reset(token)


def bound_user() -> str | None:
    """The currently bound user, or None outside an agent turn."""
    return _bound_user_id.get()


def enforce_user(supplied: str) -> str:
    """Return the user id a tool must act on.

    The bound id wins. A mismatch is logged — never raised, because the agent
    must keep working for the real user — and the supplied id is discarded.
    """
    bound = _bound_user_id.get()
    if bound is None:
        return supplied
    if supplied != bound:
        logger.warning("tenant_mismatch", user_id=bound, supplied_user_id=supplied)
    return bound
