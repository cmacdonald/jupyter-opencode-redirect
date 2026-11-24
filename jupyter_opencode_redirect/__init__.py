"""Jupyter Server extension exposing a command-driven ``/opencode`` redirect."""

from .extension import (
    ENV_QUERY,
    ENV_REQUEST_URI,
    CommandError,
    OpenCodeRedirect,
    OpenCodeRedirectHandler,
    PublicOpenCodeRedirectHandler,
    resolve_redirect_target,
    run_command,
    validate_target,
)

__version__ = "0.1.0"

__all__ = [
    "ENV_QUERY",
    "ENV_REQUEST_URI",
    "CommandError",
    "OpenCodeRedirect",
    "OpenCodeRedirectHandler",
    "PublicOpenCodeRedirectHandler",
    "__version__",
    "resolve_redirect_target",
    "run_command",
    "validate_target",
]


def _jupyter_server_extension_points():
    return [{"module": "jupyter_opencode_redirect", "app": OpenCodeRedirect}]
