import os

import pytest

from jupyter_opencode_redirect import (
    ENV_QUERY,
    CommandError,
    resolve_redirect_target,
    validate_target,
)


def test_entry_point_is_registered():
    from importlib.metadata import entry_points

    eps = entry_points()
    group = (
        eps.select(group="jupyter_server.extension")
        if hasattr(eps, "select")
        else eps.get("jupyter_server.extension", [])
    )
    found = {ep.name: ep.value for ep in group}
    assert found.get("jupyter_opencode_redirect") == "jupyter_opencode_redirect"


def test_uses_last_non_empty_stdout_line():
    target = resolve_redirect_target("printf 'noise\\n\\nhttps://example.com/a?b=1\\n\\n'", 5)
    assert target == "https://example.com/a?b=1"


def test_strips_surrounding_whitespace():
    target = resolve_redirect_target("printf '  https://example.com/x  \\n'", 5)
    assert target == "https://example.com/x"


def test_rejects_empty_output():
    with pytest.raises(CommandError, match="no output"):
        resolve_redirect_target("true", 5)


def test_rejects_non_http_scheme():
    with pytest.raises(CommandError, match="http or https"):
        resolve_redirect_target("echo file:///etc/passwd", 5)


def test_rejects_missing_host():
    with pytest.raises(CommandError, match="missing a host"):
        resolve_redirect_target("echo https:///nope", 5)


@pytest.mark.parametrize(
    "target",
    ["https://example.com/a b", "https://example.com/\x01", "https://example.com/\x7f"],
)
def test_rejects_whitespace_and_control_characters(target):
    with pytest.raises(CommandError, match="whitespace or control"):
        validate_target(target)


def test_nonzero_exit_reports_stderr():
    with pytest.raises(CommandError, match="status 3: boom"):
        resolve_redirect_target("echo boom >&2; exit 3", 5)


def test_timeout_answers_504():
    with pytest.raises(CommandError) as excinfo:
        resolve_redirect_target("sleep 30", 0.2)
    assert excinfo.value.status_code == 504
    assert "timed out" in str(excinfo.value)


def test_command_receives_request_query_in_environment():
    command = 'printf "https://example.com/?q=%s" "$' + ENV_QUERY + '"'
    env = {**os.environ, ENV_QUERY: "session=abc"}
    target = resolve_redirect_target(command, 5, env)
    assert target == "https://example.com/?q=session=abc"


@pytest.fixture
def jp_server_config(jp_server_config, request):
    """Enable the extension and apply per-test trait values."""
    jp_server_config.ServerApp.jpserver_extensions["jupyter_opencode_redirect"] = True
    for key, value in getattr(request, "param", {}).items():
        setattr(jp_server_config.OpenCodeRedirect, key, value)
    return jp_server_config


@pytest.mark.parametrize(
    "jp_server_config",
    [{"command": "printf 'diagnostic line\\nhttps://example.com/target\\n'"}],
    indirect=True,
)
async def test_endpoint_issues_302(jp_fetch):
    response = await jp_fetch("opencode", follow_redirects=False, raise_error=False)
    assert response.code == 302
    assert response.headers["Location"] == "https://example.com/target"
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "jp_server_config",
    [{"command": 'printf "https://example.com/?%s" "$JUPYTER_OPENCODE_REDIRECT_QUERY"'}],
    indirect=True,
)
async def test_request_query_is_passed_to_command(jp_fetch):
    response = await jp_fetch(
        "opencode",
        params={"session": "abc"},
        follow_redirects=False,
        raise_error=False,
    )
    assert response.code == 302
    assert response.headers["Location"] == "https://example.com/?session=abc"


@pytest.mark.parametrize(
    "jp_server_config",
    [{"command": "echo nope >&2; exit 7"}],
    indirect=True,
)
async def test_command_failure_answers_500(jp_fetch):
    response = await jp_fetch("opencode", follow_redirects=False, raise_error=False)
    assert response.code == 500


@pytest.mark.parametrize(
    "jp_server_config",
    [{"command": "echo https://example.com/"}],
    indirect=True,
)
async def test_requires_authentication_by_default(jp_fetch):
    response = await jp_fetch(
        "opencode",
        headers={"Authorization": ""},
        follow_redirects=False,
        raise_error=False,
    )
    assert response.code == 302
    assert "login" in response.headers["Location"]
    assert "next=" in response.headers["Location"]


@pytest.mark.parametrize(
    "jp_server_config",
    [{"command": "echo https://example.com/", "require_auth": False}],
    indirect=True,
)
async def test_can_be_made_public(jp_fetch):
    response = await jp_fetch(
        "opencode",
        headers={"Authorization": ""},
        follow_redirects=False,
        raise_error=False,
    )
    assert response.code == 302
    assert response.headers["Location"] == "https://example.com/"
