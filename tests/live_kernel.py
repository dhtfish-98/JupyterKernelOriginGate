"""Real Jupyter Server and ipykernel verification for the authorization gate.

Runs only against disposable local servers and executes the expression 6 * 7.
Generated files and logs go under the supplied Build directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import socket
import sys
import uuid
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSServerHandshakeError, WSMsgType
from multidict import CIMultiDict


def unused_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LocalJupyter:
    def __init__(self, root: Path, guarded: bool) -> None:
        self.root = root
        self.guarded = guarded
        self.port = unused_loopback_port()
        self.token = secrets.token_urlsafe(36)
        self.origin = f"http://127.0.0.1:{self.port}"
        self.base = self.origin
        self.proc: asyncio.subprocess.Process | None = None
        self.log_file = None

    async def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        if env.get("PYTHONPATH"):
            env["PYTHONPATH"] = os.pathsep.join(
                str(Path(part).resolve())
                for part in env["PYTHONPATH"].split(os.pathsep)
                if part
            )
        for name, path in {
            "JUPYTER_CONFIG_DIR": self.root / "config",
            "JUPYTER_DATA_DIR": self.root / "data",
            "JUPYTER_RUNTIME_DIR": self.root / "runtime",
            "IPYTHONDIR": self.root / "ipython",
            "TMPDIR": self.root / "tmp",
        }.items():
            path.mkdir(parents=True, exist_ok=True)
            env[name] = str(path)
        env["JUPYTER_TOKEN"] = self.token
        if self.guarded:
            env["JKG_ALLOWED_ORIGIN"] = self.origin
        args = [
            sys.executable,
            "-m",
            "jupyter_server",
            "--ServerApp.open_browser=False",
            "--ServerApp.ip=127.0.0.1",
            f"--ServerApp.port={self.port}",
            "--ServerApp.port_retries=0",
            f"--ServerApp.root_dir={self.root / 'notebooks'}",
            "--ServerApp.terminals_enabled=False",
            "--ServerApp.allow_unauthenticated_access=False",
        ]
        (self.root / "notebooks").mkdir(exist_ok=True)
        if self.guarded:
            args.append(
                "--ServerApp.authorizer_class="
                "jupyter_kernel_origin_gate.authorizer.KernelOriginAuthorizer"
            )
        self.log_file = (self.root / "server.log").open("wb")
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=self.root,
            env=env,
            stdout=self.log_file,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        timeout = ClientTimeout(total=2)
        async with ClientSession(timeout=timeout) as client:
            for _ in range(80):
                if self.proc.returncode is not None:
                    raise RuntimeError("Jupyter Server exited; inspect Build server.log")
                try:
                    async with client.get(
                        f"{self.base}/api/kernels",
                        headers=auth_headers(self.token, self.origin),
                    ) as response:
                        if response.status == 200:
                            return
                except (OSError, asyncio.TimeoutError):
                    pass
                await asyncio.sleep(0.25)
        raise TimeoutError("Jupyter Server was not ready; inspect Build server.log")

    async def stop(self) -> None:
        if self.proc is not None and self.proc.returncode is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(self.proc.wait(), 7)
            except asyncio.TimeoutError:
                os.killpg(self.proc.pid, signal.SIGKILL)
                await self.proc.wait()
        if self.log_file is not None:
            self.log_file.close()


def auth_headers(token: str, origin: str | None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if origin is not None:
        headers["Origin"] = origin
    return headers


async def create_kernel(client: ClientSession, server: LocalJupyter, origin: str) -> str:
    async with client.post(
        f"{server.base}/api/kernels",
        headers={**auth_headers(server.token, origin), "Content-Type": "application/json"},
        json={"name": "python3"},
    ) as response:
        body = await response.text()
        assert response.status == 201, (response.status, body[:200])
        model = json.loads(body)
        assert model["name"] == "python3"
        return model["id"]


async def kernel_count(client: ClientSession, server: LocalJupyter) -> int:
    async with client.get(
        f"{server.base}/api/kernels", headers=auth_headers(server.token, server.origin)
    ) as response:
        assert response.status == 200, response.status
        return len(await response.json())


async def rejected_kernel_creation(
    client: ClientSession, server: LocalJupyter, *, origin: str | None, token: str | None
) -> int:
    headers = auth_headers(token, origin) if token else {}
    if origin is not None:
        headers["Origin"] = origin
    async with client.post(
        f"{server.base}/api/kernels", headers=headers, json={"name": "python3"}
    ) as response:
        assert response.status in {401, 403}, response.status
        return response.status


async def kernel_connections(client: ClientSession, server: LocalJupyter, kernel_id: str) -> int:
    async with client.get(
        f"{server.base}/api/kernels/{kernel_id}",
        headers=auth_headers(server.token, server.origin),
    ) as response:
        assert response.status == 200, response.status
        model = await response.json()
        return model["connections"]


async def execute_harmless_expression(
    client: ClientSession, server: LocalJupyter, kernel_id: str, origin: str
) -> str:
    session = uuid.uuid4().hex
    message_id = uuid.uuid4().hex
    url = f"{server.base.replace('http:', 'ws:')}/api/kernels/{kernel_id}/channels?session_id={session}"
    async with client.ws_connect(url, headers=auth_headers(server.token, origin), timeout=12) as ws:
        request = {
            "header": {
                "msg_id": message_id,
                "username": "local-lab",
                "session": session,
                "msg_type": "execute_request",
                "version": "5.3",
            },
            "parent_header": {},
            "metadata": {},
            "content": {
                "code": "6 * 7",
                "silent": False,
                "store_history": False,
                "user_expressions": {},
                "allow_stdin": False,
                "stop_on_error": True,
            },
            "channel": "shell",
        }
        await ws.send_json(request)
        for _ in range(80):
            event = await ws.receive(timeout=12)
            if event.type == WSMsgType.TEXT:
                packet = json.loads(event.data)
                if packet.get("parent_header", {}).get("msg_id") != message_id:
                    continue
                if packet.get("msg_type") == "execute_result":
                    return packet["content"]["data"]["text/plain"]
                if packet.get("msg_type") == "error":
                    raise AssertionError("Kernel returned an error")
            elif event.type in {WSMsgType.CLOSED, WSMsgType.ERROR, WSMsgType.CLOSE}:
                raise AssertionError("Kernel WebSocket closed before an execution result")
    raise TimeoutError("No execution result from real ipykernel")


async def rejected_websocket(
    client: ClientSession,
    server: LocalJupyter,
    kernel_id: str,
    *,
    origin: str | None,
    token: str | None,
    query_token: bool = False,
    duplicate_origin: bool = False,
    duplicate_authorization: bool = False,
) -> int:
    url = f"{server.base.replace('http:', 'ws:')}/api/kernels/{kernel_id}/channels"
    if query_token:
        url += f"?token={server.token}"
    headers = auth_headers(token, origin) if token else {}
    if origin is not None:
        headers["Origin"] = origin
    if duplicate_origin:
        headers = CIMultiDict(
            [("Authorization", f"Bearer {token}"), ("Origin", server.origin),
             ("Origin", "https://other-origin.example.test")]
        )
    if duplicate_authorization:
        headers = CIMultiDict(
            [("Origin", server.origin), ("Authorization", f"Bearer {token}"),
             ("Authorization", "Bearer invalid-token")]
        )
    try:
        async with client.ws_connect(url, headers=headers, timeout=6):
            raise AssertionError("Unauthorized WebSocket unexpectedly opened")
    except WSServerHandshakeError as error:
        assert error.status in {401, 403}, error.status
        return error.status


async def run(build: Path) -> dict[str, object]:
    baseline = LocalJupyter(build / "baseline", guarded=False)
    gate = LocalJupyter(build / "gate", guarded=True)
    results: dict[str, object] = {}
    timeout = ClientTimeout(total=20)
    try:
        await baseline.start()
        async with ClientSession(timeout=timeout) as client:
            kernel_id = await create_kernel(client, baseline, baseline.origin)
            result = await execute_harmless_expression(
                client, baseline, kernel_id, "https://other-origin.example.test"
            )
            assert result == "42", result
            results["baseline_cross_origin_real_kernel_result"] = result
            async with client.delete(
                f"{baseline.base}/api/kernels/{kernel_id}",
                headers=auth_headers(baseline.token, baseline.origin),
            ) as response:
                assert response.status == 204, response.status
        await baseline.stop()

        await gate.start()
        async with ClientSession(timeout=timeout) as client:
            assert await kernel_count(client, gate) == 0
            denied_creation = {}
            denied_creation["cross_origin"] = await rejected_kernel_creation(
                client, gate, origin="https://other-origin.example.test", token=gate.token
            )
            denied_creation["wrong_token"] = await rejected_kernel_creation(
                client, gate, origin=gate.origin, token="invalid-token"
            )
            denied_creation["missing_origin"] = await rejected_kernel_creation(
                client, gate, origin=None, token=gate.token
            )
            assert await kernel_count(client, gate) == 0
            results["denied_creation_status"] = denied_creation
            results["kernels_after_denied_creation"] = 0
            kernel_id = await create_kernel(client, gate, gate.origin)
            connections_before = await kernel_connections(client, gate, kernel_id)
            assert connections_before == 0, connections_before
            denied = {}
            denied["cross_origin"] = await rejected_websocket(
                client, gate, kernel_id, origin="https://other-origin.example.test", token=gate.token
            )
            denied["wrong_token"] = await rejected_websocket(
                client, gate, kernel_id, origin=gate.origin, token="invalid-token"
            )
            denied["missing_origin"] = await rejected_websocket(
                client, gate, kernel_id, origin=None, token=gate.token
            )
            denied["query_token_only"] = await rejected_websocket(
                client, gate, kernel_id, origin=gate.origin, token=None, query_token=True
            )
            denied["query_token_and_header"] = await rejected_websocket(
                client, gate, kernel_id, origin=gate.origin, token=gate.token, query_token=True
            )
            denied["duplicate_origin"] = await rejected_websocket(
                client, gate, kernel_id, origin=gate.origin, token=gate.token,
                duplicate_origin=True
            )
            denied["duplicate_authorization"] = await rejected_websocket(
                client, gate, kernel_id, origin=gate.origin, token=gate.token,
                duplicate_authorization=True
            )
            connections_after = await kernel_connections(client, gate, kernel_id)
            assert connections_after == connections_before, (connections_before, connections_after)
            results["denied_websocket_status"] = denied
            results["connections_before_denied"] = connections_before
            results["connections_after_denied"] = connections_after
            result = await execute_harmless_expression(client, gate, kernel_id, gate.origin)
            assert result == "42", result
            results["guarded_same_origin_real_kernel_result"] = result
            async with client.get(
                f"{gate.base}/api/sessions", headers=auth_headers(gate.token, gate.origin)
            ) as response:
                results["sessions_resource_status"] = response.status
                assert response.status == 403, response.status
            async with client.delete(
                f"{gate.base}/api/kernels/{kernel_id}",
                headers=auth_headers(gate.token, gate.origin),
            ) as response:
                assert response.status == 204, response.status
    finally:
        await baseline.stop()
        await gate.stop()
    results["jupyter_server_version"] = __import__("jupyter_server").__version__
    results["ipykernel_version"] = __import__("ipykernel").__version__
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, required=True)
    args = parser.parse_args()
    output = asyncio.run(run(args.build_dir.resolve()))
    print(json.dumps(output, indent=2, sort_keys=True))
