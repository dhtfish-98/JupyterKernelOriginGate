# JupyterKernelOriginGate

Version 0.1.0. Author of the new policy and validation code: **dhtfish98**.

This is a narrow, single-user Jupyter Server authorizer for a headless kernel API. Jupyter authenticates the request first. The added policy then requires one configured HTTP(S) `Origin` and an exact `Authorization: Bearer` token on kernel REST requests and the kernel WebSocket. It refuses query-token and cookie-only access to that API. Other Jupyter resources, including sessions and terminals, are denied by the authorizer. This is defense in depth for a deployment that deliberately wants a single authorized origin and explicit API credentials.

The project does not modify or bundle Jupyter Server. The upstream Jupyter Server project and its BSD-3-Clause rights are identified in [ORIGIN.md](ORIGIN.md). The MIT license applies to this project's original files only.

## Run the local proof

Use Python 3.11 or newer. The following commands work from this repository's root:

```sh
python -m pip install '.[test]'
python tests/live_kernel.py --build-dir Build/验证/live-kernel
python -m build --outdir Build/dist
```

The test starts two disposable Jupyter Server processes and real `ipykernel` processes bound to loopback. On the baseline server, a client holding the valid token can open a cross-origin WebSocket and evaluate only `6 * 7`. On the guarded server, same-origin and correct bearer credentials evaluate `6 * 7`; wrong-origin, missing-origin, invalid-token, query-token, and duplicate-header handshakes receive 403 before the connection count increases. Cross-origin and invalid-token kernel-creation requests also receive 403 before a kernel starts. Generated state and server logs stay under `Build`.

## Configure the policy

Set `JUPYTER_TOKEN` to a random token of at least 32 characters and `JKG_ALLOWED_ORIGIN` to the exact origin of the trusted client. Install this project in the same Python environment as Jupyter Server, then start a **headless, single-user** server with:

```sh
python -m jupyter_server \
  --ServerApp.authorizer_class=jupyter_kernel_origin_gate.authorizer.KernelOriginAuthorizer \
  --ServerApp.terminals_enabled=False \
  --ServerApp.allow_unauthenticated_access=False \
  --ServerApp.ip=127.0.0.1 \
  --ServerApp.open_browser=False
```

The token and origin are read from the environment; keep the token out of command arguments, URLs, and logs. The authorizer fails server startup if the origin is malformed or the token is too short. A normal browser WebSocket API cannot set an `Authorization` header, so this package targets explicit API clients; it does not provide a drop-in Jupyter browser UI.

`Origin` is a browser context signal, not proof of identity. Nonbrowser clients can forge it. Token secrecy and Jupyter's own authentication remain necessary. The policy is not a multi-user isolation system, a replacement for TLS, or a claim that Jupyter Server has a vulnerability. See [THREAT_MODEL.md](THREAT_MODEL.md) for the precise boundary and [VALIDATION.md](VALIDATION.md) for the reproducible checks.
