# Validation contract

Run `python tests/live_kernel.py --build-dir Build/验证/live-kernel` after installing `.[test]` from the repository root. The test exits nonzero unless all checks below pass against disposable loopback Jupyter Server and ipykernel processes:

1. The baseline, with a valid token and a different `Origin`, opens a kernel WebSocket and obtains `42` from `6 * 7`.
2. The guarded server refuses cross-origin, missing-origin, and invalid-token kernel creation; its kernel count remains zero.
3. A trusted-origin bearer client starts one real Python kernel. Seven WebSocket handshakes—cross-origin, missing-origin, wrong-token, query-token-only, query-token plus bearer, duplicate origin, and duplicate authorization—are rejected with 401 or 403. Its Jupyter kernel connection count remains zero.
4. A trusted-origin bearer WebSocket executes `6 * 7` and receives `42` from the real kernel. The sessions resource receives 403.

The script does not generate or run harmful notebook code. It creates runtime files and logs only below the selected `Build` directory and stops its server processes. A passing local test is a local integration result, not proof of external deployment or CVP acceptance.
