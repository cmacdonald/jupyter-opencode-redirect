# jupyter-opencode-redirect

A Jupyter Server extension that exposes exactly one endpoint:

```
GET <base_url>/opencode  ->  HTTP 302
```

The `Location` header is whatever URL a shell command of your choosing prints.
That makes the destination dynamic: it can point at a locally running
`opencode` server, a tunnel, or anything else that is only known at request
time.

## Install

```bash
pip install jupyter-opencode-redirect
```

or, from a checkout:

```bash
pip install -e .
```

Enable the extension in `jupyter_server_config.py`:

```python
c.ServerApp.jpserver_extensions = {"jupyter_opencode_redirect": True}
```

`jupyter server extension list` should then report the extension as enabled.

## Configure

```python
c.OpenCodeRedirect.command = "echo https://opencode.ai"  # default: "echo http://localhost:4096"
c.OpenCodeRedirect.timeout = 10.0                         # seconds, default 10
c.OpenCodeRedirect.require_auth = True                    # default True
```

### Command contract

* The command runs through the shell (`/bin/sh` on POSIX) with the server's
  environment plus the variables below.
* Its **last non-empty stdout line** must be an absolute `http://` or `https://`
  URL. Earlier lines may contain diagnostics.
* A non-zero exit status answers `500`; exceeding `timeout` answers `504`
  (the whole process group is killed).
* Output that is not a single, whitespace-free `http(s)` URL answers `500`.
  Redirecting to `javascript:`, `file:`, or protocol-relative URLs is refused.
* Responses carry `Cache-Control: no-store`, so the command runs on every
  request.

### Environment passed to the command

| Variable | Value |
| --- | --- |
| `JUPYTER_OPENCODE_REDIRECT_REQUEST_URI` | Request path and query, e.g. `/opencode?session=abc` |
| `JUPYTER_OPENCODE_REDIRECT_QUERY` | Raw query string, e.g. `session=abc` |

Both are plain environment values, never interpolated into the command by the
extension, so reading them (for example `"$JUPYTER_OPENCODE_REDIRECT_QUERY"`)
does not let a caller inject shell syntax. Building shell code by pasting the
query string into it yourself would.

Example: redirect to a local server, preserving the caller's query string.

```python
c.OpenCodeRedirect.command = (
    'printf "http://localhost:4096/?%s" "$JUPYTER_OPENCODE_REDIRECT_QUERY"'
)
```

## Security notes

* The endpoint is authenticated by default: unauthenticated browsers are sent
  to the Jupyter login page and back. Set `c.OpenCodeRedirect.require_auth =
  False` only for an intentionally public endpoint.
* The command runs with the privileges of the Jupyter server. Treat
  `c.OpenCodeRedirect.command` as trusted configuration, not user input.
* Error responses include the command's last stderr line to make failures
  debuggable. If the endpoint is public, keep that in mind.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

## License

MIT
