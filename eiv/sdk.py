"""
EIV — Python SDK for agent integration

Two client modes:

  EivClient   — HTTP client targeting a running EIV API server.
  EivEmbed    — In-process validation (no server needed).

Both expose the same three core methods:
  validate(intent, tx_ref)         -> validation record
  gate(intent, proposed_tx)        -> gate decision
  reputation(agent_address)        -> trust profile

Async wrappers:
  AsyncEivClient wraps EivClient (or EivEmbed) and runs calls in a
  ThreadPoolExecutor so they can be awaited.

Hooks:
  Register post-validation callbacks via on_validation(callback).
  Callbacks receive the full validation/gate result dict.

Usage (HTTP client)::

    from eiv.sdk import EivClient

    client = EivClient("http://127.0.0.1:8000")
    result = client.validate(intent_dict, "0xabc...")
    print(result["verdict"])

Usage (embedded, no server)::

    from eiv.sdk import EivEmbed

    eiv = EivEmbed()                     # uses MockChainAdapter
    eiv = EivEmbed(rpc_url="https://...")  # uses RpcChainAdapter
    result = eiv.validate(intent_dict, "0xabc...")

Usage (async)::

    from eiv.sdk import AsyncEivClient, EivClient

    async def main():
        client = AsyncEivClient(EivClient("http://127.0.0.1:8000"))
        result = await client.validate(intent, tx_ref)
"""

from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

from eiv.reputation import compute_reputation


_Hook = Callable[[dict], None]


class _HookMixin:
    """Post-validation hook support shared by all client types."""

    def __init__(self) -> None:
        self._hooks: list[_Hook] = []

    def on_validation(self, callback: _Hook) -> None:
        self._hooks.append(callback)

    def _fire_hooks(self, record: dict) -> None:
        for hook in self._hooks:
            try:
                hook(record)
            except Exception:
                pass


class EivClient(_HookMixin):
    """HTTP client for a remote EIV API server."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 30) -> None:
        _HookMixin.__init__(self)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self.base_url + path
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def validate(self, intent: dict, tx_ref: str) -> dict:
        result = self._request("POST", "/validate", {"intent": intent, "tx_ref": tx_ref})
        self._fire_hooks(result)
        return result

    def gate(self, intent: dict, proposed_tx: dict) -> dict:
        result = self._request("POST", "/gate", {"intent": intent, "proposed_tx": proposed_tx})
        self._fire_hooks(result)
        return result

    def reputation(self, agent_address: str) -> dict:
        return self._request("GET", f"/reputation/{agent_address}")

    def get_validation(self, validation_id: str) -> dict:
        return self._request("GET", f"/validations/{validation_id}")

    def list_validations(self) -> list[dict]:
        return self._request("GET", "/validations").get("validations", [])

    def health(self) -> dict:
        return self._request("GET", "/healthz")

    def status(self) -> dict:
        return self._request("GET", "/status")


class EivEmbed(_HookMixin):
    """In-process validation — no HTTP server needed.

    Builds a ValidatorService internally. Pass rpc_url for live-chain
    validation, or leave blank for MockChainAdapter (fixture-based).
    """

    def __init__(
        self,
        rpc_url: str = "",
        store_dir: Optional[str] = None,
        require_signature: bool = False,
    ) -> None:
        _HookMixin.__init__(self)
        from eiv.chain_adapter import MockChainAdapter, RpcChainAdapter
        from eiv.eip712 import Eip712Verifier
        from eiv.intent_source import IntentSource
        from eiv.service import ValidatorService
        from eiv.store import ValidationStore

        adapter = RpcChainAdapter(rpc_url) if rpc_url else MockChainAdapter()
        verifier = Eip712Verifier(require_signature=require_signature)
        self._service = ValidatorService(
            source=IntentSource(verifier=verifier),
            adapter=adapter,
            store=ValidationStore(store_dir),
        )

    def validate(self, intent: dict, tx_ref: str) -> dict:
        record = self._service.run(intent, tx_ref)
        result = {
            "validation_id": record["validation_id"],
            "verdict": record["result"]["verdict"],
            "violations": record["result"]["violations"],
        }
        self._fire_hooks(result)
        return result

    def gate(self, intent: dict, proposed_tx: dict) -> dict:
        result = self._service.gate(intent, proposed_tx)
        self._fire_hooks(result)
        return result

    def reputation(self, agent_address: str) -> dict:
        store = self._service.store
        records = store.list()
        agent_records = [r for r in records if r.get("signer") == agent_address]
        return compute_reputation(agent_records, agent_address)


class AsyncEivClient:
    """Async wrapper — runs any sync client (EivClient or EivEmbed) in a thread pool."""

    def __init__(self, client: EivClient | EivEmbed, max_workers: int = 4) -> None:
        self._client = client
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def on_validation(self, callback: _Hook) -> None:
        self._client.on_validation(callback)

    async def validate(self, intent: dict, tx_ref: str) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._client.validate, intent, tx_ref)

    async def gate(self, intent: dict, proposed_tx: dict) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._client.gate, intent, proposed_tx)

    async def reputation(self, agent_address: str) -> dict:
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, self._client.reputation, agent_address)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False)
