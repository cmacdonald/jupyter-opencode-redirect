"""Redirect ``/opencode`` to a URL printed by a shell command.

The extension exposes a single GET endpoint.  For every request it runs the
configured command and answers with an HTTP 302 whose ``Location`` header is the
last non-empty line of the command's stdout.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
from typing import Dict, Optional
from urllib.parse import urlsplit

from jupyter_server.auth.decorator import allow_unauthenticated
from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.extension.application import ExtensionApp
from tornado import web
from traitlets import Bool, Float, Unicode

ENV_REQUEST_URI = "JUPYTER_OPENCODE_REDIRECT_REQUEST_URI"
ENV_QUERY = "JUPYTER_OPENCODE_REDIRECT_QUERY"

ALLOWED_SCHEMES = frozenset({"http", "https"})


class CommandError(Exception):
    """The redirect command could not produce a usable redirect target."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = status_code


def run_command(
    command: str,
    timeout: float,
    env: Optional[Dict[str, str]] = None,
) -> "subprocess.CompletedProcess[str]":
    """Run *command* in a shell, killing its whole process group on timeout."""
    extra_kwargs = {}
    if os.name == "posix":
        # Put the shell and its children in their own process group so a
        # timeout can kill the entire pipeline, not just the shell.
        extra_kwargs["start_new_session"] = True

    process = subprocess.Popen(
        command,
        shell=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **extra_kwargs,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
        else:
            process.kill()
        process.communicate()
        raise CommandError(
            f"Redirect command timed out after {timeout:g}s: {command}", 504
        ) from None
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def validate_target(target: str) -> str:
    target = f"http://{os.environ['HOSTNAME']}-agent.craigm.apps.os.dcs.gla.ac.uk/{target}"

    """Return *target* if it is a safe absolute http(s) URL."""
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in target):
        raise CommandError(
            f"Redirect target contains whitespace or control characters: {target!r}"
        )
    try:
        parsed = urlsplit(target)
        hostname = parsed.hostname
    except ValueError as exc:
        raise CommandError(f"Redirect target is not a valid URL: {target!r}") from exc
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise CommandError(f"Redirect target must use http or https: {target!r}")
    if not hostname:
        raise CommandError(f"Redirect target is missing a host: {target!r}")
    return target


def resolve_redirect_target(
    command: str,
    timeout: float,
    env: Optional[Dict[str, str]] = None,
) -> str:
    """Run *command* and return the validated URL from its stdout.

    The last non-empty stdout line is used, so a command is free to print
    diagnostics before the URL.
    """
    result = run_command(command, timeout, env)
    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        detail = f": {stderr_lines[-1]}" if stderr_lines else ""
        raise CommandError(
            f"Redirect command exited with status {result.returncode}{detail}"
        )

    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines:
        raise CommandError("Redirect command produced no output")
    return validate_target(lines[-1])


class _OpenCodeRedirectHandler(JupyterHandler):
    """Shared implementation for the authenticated and public handlers."""

    def initialize(self, command: str, timeout: float) -> None:
        self._command = command
        self._timeout = timeout

    async def _redirect_to_target(self) -> None:
        env = os.environ.copy()
        env[ENV_REQUEST_URI] = self.request.uri
        env[ENV_QUERY] = self.request.query

        try:
            # The command may block, so keep it off the IOLoop thread.
            target = await asyncio.to_thread(
                resolve_redirect_target, self._command, self._timeout, env
            )
        except CommandError as exc:
            self.log.error("Redirect failed for %s: %s", self.request.uri, exc)
            raise web.HTTPError(exc.status_code, str(exc)) from exc

        self.log.debug("Redirecting %s to %s", self.request.uri, target)
        # The destination is resolved per request, so never let it be cached.
        self.set_header("Cache-Control", "no-store")
        self.redirect(target)


class OpenCodeRedirectHandler(_OpenCodeRedirectHandler):
    """Handler used when authentication is required (the default)."""

    @web.authenticated
    async def get(self) -> None:
        await self._redirect_to_target()


class PublicOpenCodeRedirectHandler(_OpenCodeRedirectHandler):
    """Handler used when ``require_auth`` is disabled."""

    @allow_unauthenticated
    async def get(self) -> None:
        await self._redirect_to_target()


class OpenCodeRedirect(ExtensionApp):
    """Jupyter Server extension serving the ``/opencode`` redirect endpoint."""

    name = "jupyter_opencode_redirect"
    description = __doc__

    command = Unicode(
        #default_value="echo http://localhost:4096",
        default_value='echo "opencode pair 2>/dev/null| grep 127.0.0.1 | cut -f4- -d/',
        help="""Shell command used to resolve the redirect target.

        The last non-empty line of stdout must be an absolute http(s) URL.
        The incoming request is described by the JUPYTER_OPENCODE_REDIRECT_*
        environment variables (request URI and raw query string).""",
    ).tag(config=True)

    timeout = Float(
        default_value=10.0,
        help="Seconds to wait for the redirect command before answering 504.",
    ).tag(config=True)

    require_auth = Bool(
        default_value=True,
        help="""Require an authenticated Jupyter user for the endpoint.

        Disable only if the endpoint is meant to be publicly reachable; the
        configured command runs with the server's privileges.""",
    ).tag(config=True)

    def initialize_handlers(self) -> None:
        handler = (
            OpenCodeRedirectHandler if self.require_auth else PublicOpenCodeRedirectHandler
        )
        self.handlers.append(
            (
                r"/opencode/?",
                handler,
                {"command": self.command, "timeout": self.timeout},
            )
        )
