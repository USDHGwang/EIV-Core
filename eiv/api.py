"""
EIV — HTTP API + embedded console (standard library, zero dependencies)

Endpoints (JSON):
  POST /validate     body {"intent": {...}, "tx_ref": "..."}  -> {"validation_id", "verdict"}
  POST /gate         body {"intent": {...}, "proposed_tx": {...}} -> {"decision", "result"}
  GET  /validations                                            -> {"validations": [summary...]}
  GET  /validations/{id}                                       -> full record (incl. result schema)
  GET  /reputation/{addr}                                      -> trust profile for an agent address
  GET  /scenarios                                              -> bundled demo scenarios (intent inlined)
  GET  /status                                                 -> component implementations + counters
  GET  /healthz                                                -> {"status": "ok"}

Endpoints (HTML):
  GET  /             -> the EIV console (eiv/static/index.html), a zero-dependency
                        web UI over the same API.

Run: python -m eiv.api  or  python eiv/api.py --port 8000

Production implementations are activated through the environment (see
service_from_env / .env.example): RPC_URL switches the trace source to a live
node; EIV_VALIDATION_REGISTRY_ADDRESS + ATTESTER_PRIVATE_KEY switch attestation
to the on-chain ERC-8004 registry (EIV_ATTEST_DRY_RUN=1 signs without
broadcasting). Without configuration the reference implementations run, so the
service always starts.

CORS is enabled (for cross-origin browser access), including OPTIONS preflight.
"""

from __future__ import annotations

import os
import sys

# Path setup so this file finds the eiv package whether run via -m or directly.
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # parent dir of the package
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

# Windows consoles may default to a non-UTF-8 codepage; force UTF-8 output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from eiv import __version__
from eiv.attestation import OnChainAttestationSink, StubAttestationSink
from eiv.chain_adapter import MockChainAdapter, RpcChainAdapter, TraceNotFound
from eiv.intent_source import IntentAuthError, IntentSource
from eiv.schema import AddressPinningError, IntentParseError, TraceParseError
from eiv.service import ValidatorService
from eiv.reputation import compute_reputation
from eiv.store import SqliteValidationStore, ValidationStore

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
_DEFAULT_STORE_DIR = os.path.join(_HERE, "runs")
_STATIC_INDEX = os.path.join(_HERE, "static", "index.html")
_DASHBOARD_DIR = os.path.join(_PROJECT_ROOT, "dashboard")
_SCENARIOS_FILE = os.path.join(_HERE, "fixtures", "scenarios.json")
_INTENTS_DIR = os.path.join(_HERE, "fixtures", "intents")


def load_scenarios() -> list:
    """Bundled demo scenarios with their intent JSON inlined."""
    try:
        with open(_SCENARIOS_FILE, encoding="utf-8") as f:
            scenarios = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for sc in scenarios:
        sc = dict(sc)
        intent_file = sc.pop("intent_file", None)
        if intent_file:
            path = os.path.join(_INTENTS_DIR, os.path.basename(intent_file))
            try:
                with open(path, encoding="utf-8") as f:
                    sc["intent"] = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
        out.append(sc)
    return out


def service_from_env(store_dir: str | None = None) -> ValidatorService:
    """Compose a ValidatorService from environment configuration.

    Unset variables fall back to the reference implementations, so the service
    always starts; each component upgrades independently:
      RPC_URL                          -> RpcChainAdapter (live trace decoding)
      EIV_VALIDATION_REGISTRY_ADDRESS
        + ATTESTER_PRIVATE_KEY         -> OnChainAttestationSink (ERC-8004 write)
      EIV_ATTEST_DRY_RUN=1             -> sign the attestation tx but don't broadcast
      EIV_RESPONSE_URI_BASE            -> responseURI prefix for attestations
      CHAIN_ID                         -> EIP-712 domain / tx chain id
      EIV_REQUIRE_SIGNATURE=1          -> reject unsigned intents
      EIV_STORE_BACKEND=sqlite         -> SqliteValidationStore (default: json)
    """
    rpc_url = os.environ.get("RPC_URL", "").strip()
    adapter = RpcChainAdapter(rpc_url) if rpc_url else MockChainAdapter()

    registry = os.environ.get("EIV_VALIDATION_REGISTRY_ADDRESS", "").strip()
    attester_key = os.environ.get("ATTESTER_PRIVATE_KEY", "").strip()
    chain_id_raw = os.environ.get("CHAIN_ID", "").strip()
    chain_id = int(chain_id_raw, 0) if chain_id_raw else None
    if registry and attester_key and rpc_url:
        sink = OnChainAttestationSink(
            rpc_url=rpc_url,
            registry_address=registry,
            private_key=attester_key,
            chain_id=chain_id,
            response_uri_base=os.environ.get("EIV_RESPONSE_URI_BASE", "").strip(),
            dry_run=os.environ.get("EIV_ATTEST_DRY_RUN", "").strip() in ("1", "true", "yes"),
        )
    else:
        sink = StubAttestationSink()

    store_backend = os.environ.get("EIV_STORE_BACKEND", "").strip().lower()
    if store_backend == "sqlite":
        db_path = os.path.join(store_dir or _DEFAULT_STORE_DIR, "eiv.db")
        store = SqliteValidationStore(db_path)
    else:
        store = ValidationStore(store_dir)

    return ValidatorService(
        source=IntentSource(),
        adapter=adapter,
        sink=sink,
        store=store,
    )


def describe_service(service: ValidatorService) -> dict:
    """Implementation info for GET /status (and the console header badges)."""
    sink = service.sink
    adapter = service.adapter
    verifier = service.source.verifier
    components = {
        "verifier": {
            "impl": type(verifier).__name__,
            "scheme": getattr(verifier, "scheme", "unknown"),
            "chain_id": getattr(verifier, "chain_id", None),
            "require_signature": getattr(verifier, "require_signature", False),
        },
        "chain_adapter": {
            "impl": type(adapter).__name__,
            "mode": "rpc" if isinstance(adapter, RpcChainAdapter) else "fixtures",
            "rpc_url": getattr(adapter, "rpc_url", None),
        },
        "attestation_sink": {
            "impl": type(sink).__name__,
            "mode": (
                ("dry-run" if getattr(sink, "dry_run", False) else "on-chain")
                if isinstance(sink, OnChainAttestationSink)
                else "reference"
            ),
            "registry": getattr(sink, "registry_address", None),
            "attester": getattr(sink, "attester_address", None),
        },
    }
    records = service.store.list()
    verdicts = [r.get("result", {}).get("verdict") for r in records]
    return {
        "service": "eiv-validator",
        "version": __version__,
        "components": components,
        "counts": {
            "total": len(records),
            "pass": sum(1 for v in verdicts if v == "PASS"),
            "fail": sum(1 for v in verdicts if v == "FAIL"),
        },
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "EIV/" + __version__

    # --- helpers ---------------------------------------------------------
    @property
    def service(self) -> ValidatorService:
        return self.server.service  # type: ignore[attr-defined]

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, path: str) -> None:
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send(404, {"error": "console asset not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # concise log format
        sys.stderr.write(f"[eiv.api] {self.address_string()} {fmt % args}\n")

    # --- routes ----------------------------------------------------------
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path.rstrip("/")
            if path == "":
                self._send_html(_STATIC_INDEX)
            elif path in ("/healthz", "/health"):
                self._send(200, {"status": "ok", "service": "eiv-validator"})
            elif path == "/status":
                self._send(200, describe_service(self.service))
            elif path == "/scenarios":
                self._send(200, {"scenarios": load_scenarios()})
            elif path == "/validations":
                self._send(200, {"validations": self.service.list()})
            elif path.startswith("/validations/"):
                vid = path[len("/validations/") :]
                record = self.service.get(vid)
                if record is None:
                    self._send(404, {"error": f"validation {vid} not found"})
                else:
                    self._send(200, record)
            elif path.startswith("/reputation/"):
                agent_addr = path[len("/reputation/") :].lower()
                if not agent_addr:
                    self._send(400, {"error": "agent address required"})
                else:
                    store = self.service.store
                    if hasattr(store, "query"):
                        records = store.query(signer=agent_addr, limit=10_000)
                    else:
                        all_recs = store.list()
                        records = [r for r in all_recs if r.get("signer") == agent_addr]
                    self._send(200, compute_reputation(records, agent_addr))
            elif path == "/dashboard" or path == "/dashboard/index.html":
                self._send_html(os.path.join(_DASHBOARD_DIR, "index.html"))
            elif path == "/dashboard/index_zh.html":
                self._send_html(os.path.join(_DASHBOARD_DIR, "index_zh.html"))
            else:
                self._send(404, {"error": f"unknown path {path}"})
        except Exception as e:  # noqa: BLE001 — keep one request's error from taking down the server
            self._send(500, {"error": f"internal error: {e}"})

    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as e:
            self._send(400, {"error": f"invalid JSON body: {e}"})
            return None
        if not isinstance(body, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return None
        return body

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")

        if path == "/gate":
            return self._do_gate()
        if path == "/validate":
            return self._do_validate()
        self._send(404, {"error": f"unknown path {path}"})

    def _do_validate(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        if "intent" not in body or "tx_ref" not in body:
            self._send(400, {"error": "body requires {intent, tx_ref}"})
            return
        try:
            record = self.service.run(body["intent"], body["tx_ref"])
        except (IntentParseError, TraceParseError) as e:
            self._send(400, {"error": str(e)})
        except IntentAuthError as e:
            self._send(401, {"error": str(e)})
        except TraceNotFound as e:
            self._send(404, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"internal error: {e}"})
        else:
            self._send(200, {
                "validation_id": record["validation_id"],
                "verdict": record["result"]["verdict"],
                "violations": record["result"]["violations"],
            })

    def _do_gate(self) -> None:
        body = self._read_json_body()
        if body is None:
            return
        if "intent" not in body or "proposed_tx" not in body:
            self._send(400, {"error": "body requires {intent, proposed_tx}"})
            return
        proposed = body["proposed_tx"]
        if not isinstance(proposed, dict) or "to" not in proposed:
            self._send(400, {"error": "proposed_tx requires at least {to}"})
            return
        try:
            result = self.service.gate(body["intent"], proposed)
        except (IntentParseError, AddressPinningError) as e:
            self._send(400, {"error": str(e)})
        except IntentAuthError as e:
            self._send(401, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"internal error: {e}"})
        else:
            self._send(200, result)


def make_server(
    service: ValidatorService, host: str = "127.0.0.1", port: int = 8000
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.service = service  # type: ignore[attr-defined]
    return server


def main(argv: list | None = None) -> None:
    parser = argparse.ArgumentParser(description="EIV validator HTTP API + console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--store-dir",
        default=_DEFAULT_STORE_DIR,
        help="directory for validation records (default: eiv/runs/)",
    )
    args = parser.parse_args(argv)

    service = service_from_env(args.store_dir)
    info = describe_service(service)
    server = make_server(service, args.host, args.port)
    print(f"EIV validator started -> http://{args.host}:{args.port}")
    print(f"  console   : http://{args.host}:{args.port}/")
    print(f"  dashboard : http://{args.host}:{args.port}/dashboard")
    print("  api       : POST /validate   GET /validations   GET /validations/{id}")
    print("            GET /scenarios   GET /status        GET /healthz")
    for name, comp in info["components"].items():
        mode = comp.get("mode") or comp.get("scheme") or ""
        print(f"  {name:16}: {comp['impl']} ({mode})")
    print(f"  store   : {args.store_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        server.shutdown()


if __name__ == "__main__":
    main()
