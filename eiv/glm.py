"""
EIV — GLM integration (demo / agent layer, NOT the trust path)

GLM plays two roles around the deterministic core:

  1. spec_from_prompt()       natural-language authorization -> IntentSpec dict
                              (the human still signs it; EIP-712 stays the
                              source of authorization truth)
  2. propose_transaction()    GLM acts as the agent: given a signed intent and
                              a task, propose {to, data, value} — which EIV
                              then judges via service.gate()

Design rule: nothing in eiv.predicates / eiv.service depends on this module.
A wrong or malicious GLM output cannot corrupt a verdict — it can only
produce a transaction proposal that GATE rejects.

Configuration (.env or environment):
  GLM_API_KEY    required for live calls
  GLM_MODEL      default: glm-4.6
  GLM_BASE_URL   default: https://api.z.ai/api/paas/v4   (Z.AI endpoint)

The HTTP transport is injectable, so tests run without network or key.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Callable, Optional

from eiv.schema import (
    IntentParseError,
    build_intent_spec,
    require_eth_addresses,
)

DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4"
DEFAULT_MODEL = "glm-5.1"  # Z.AI track: the agent's core task must run on GLM-5.1

# Transport signature: (payload: dict) -> response dict (parsed JSON)
Transport = Callable[[dict], dict]


class GlmError(RuntimeError):
    """GLM call failed or returned something unusable."""


# Transient server states worth retrying (capacity / rate-limit, not auth/4xx).
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def _http_transport(
    base_url: str,
    api_key: str,
    timeout: float = 240,   # GLM-5.1 is a reasoning model; turns can be slow
    max_retries: int = 4,
    base_delay: float = 1.0,
) -> Transport:
    url = base_url.rstrip("/") + "/chat/completions"

    def call(payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
                try:
                    return json.loads(body)
                except json.JSONDecodeError as e:
                    raise GlmError(f"GLM returned non-JSON body: {body[:200]!r}") from e
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:500]
                last_err = GlmError(f"GLM HTTP {e.code}: {body}")
                if e.code not in _RETRYABLE_HTTP_CODES or attempt == max_retries:
                    raise last_err from e
            except OSError as e:  # connection reset / timeout — transient
                last_err = GlmError(f"GLM connection failed: {e}")
                if attempt == max_retries:
                    raise last_err from e
            time.sleep(base_delay * (2 ** attempt))  # exponential backoff
        raise last_err  # unreachable, satisfies type checker

    return call


class GlmClient:
    """Minimal chat client for GLM (Z.AI / open.bigmodel.cn compatible)."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        base_url: str = "",
        transport: Optional[Transport] = None,
    ) -> None:
        self.model = model or os.environ.get("GLM_MODEL", DEFAULT_MODEL)
        if transport is not None:
            self._transport = transport
        else:
            key = api_key or os.environ.get("GLM_API_KEY", "").strip()
            if not key:
                raise GlmError("GLM_API_KEY not set (put it in .env; it is gitignored)")
            base = base_url or os.environ.get("GLM_BASE_URL", DEFAULT_BASE_URL)
            self._transport = _http_transport(base, key)

    def chat(self, messages: list[dict], temperature: float = 0.0,
             empty_retries: int = 3) -> str:
        """One chat completion; returns the assistant text.

        GLM-5.1 is a reasoning model: a turn may come back with content=null and
        the substance in `reasoning`/`reasoning_content` instead, or occasionally
        empty. We fall back to the reasoning field (the action JSON is usually at
        its end) and otherwise retry, so an intermittent empty turn doesn't abort
        a long-horizon run.
        """
        last_err = "no response"
        for _ in range(empty_retries + 1):
            resp = self._transport({
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
            })
            try:
                msg = resp["choices"][0]["message"]
            except (KeyError, IndexError, TypeError) as e:
                raise GlmError(f"unexpected GLM response shape: {resp}") from e
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content
            # reasoning-model fallback: the final JSON is usually echoed at the
            # end of the reasoning trace
            reasoning = msg.get("reasoning") or msg.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                return reasoning
            last_err = f"empty content (type {type(content).__name__})"
        raise GlmError(f"GLM returned {last_err} after {empty_retries + 1} attempts")


def extract_json(text: str) -> dict:
    """Parse a JSON object out of model output (tolerates ``` fences / prose)."""
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        text = text[first_nl + 1 :] if first_nl != -1 else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise GlmError(f"no JSON object in model output: {text[:200]!r}")
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise GlmError(f"model output is not valid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise GlmError("model output JSON is not an object")
    return obj


_SPEC_SYSTEM = """You convert a user's plain-language authorization for an AI trading agent
into a strict JSON IntentSpec. Output ONLY a JSON object, no prose.

Fields (all required unless noted):
  allowed_targets   array of contract addresses the agent may call
  allowed_spenders  array of addresses that may receive ERC-20 approvals
  token_in          input token ADDRESS
  token_out         output token ADDRESS
  max_amount_in     max input amount as a base-unit integer STRING
  min_amount_out    min output amount as a base-unit integer STRING
  recipient         the only address allowed to receive the output
  deadline          unix timestamp (integer) after which execution is invalid
  require_zero_residual  boolean (default true)
  bounded_approval       boolean (default true)
  max_slippage_bps       integer or null

Rules:
- Use ONLY addresses from the provided address book. Never invent addresses.
- Token amounts: convert human units to base units using the decimals given.
- If the user names a token or venue not in the address book, you MUST NOT
  guess — put the literal string "UNRESOLVED" in that field.
"""


def spec_from_prompt(
    text: str,
    client: GlmClient,
    address_book: dict,
    now_ts: int,
    max_repair_rounds: int = 1,
) -> dict:
    """Natural language -> validated IntentSpec dict.

    `address_book` example:
      {"tokens": {"USDC": {"address": "0x...", "decimals": 6}},
       "venues": {"UniswapRouter": "0x..."},
       "recipient": "0x..."}

    The returned dict has passed build_intent_spec + require_eth_addresses;
    callers still review and SIGN it (EIP-712) before it grants anything.
    """
    user_msg = (
        f"Address book (the ONLY addresses you may use):\n"
        f"{json.dumps(address_book, indent=2)}\n\n"
        f"Current unix time: {now_ts}\n\n"
        f"User authorization, in their own words:\n{text}"
    )
    messages = [
        {"role": "system", "content": _SPEC_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    last_err: Exception | None = None
    for _ in range(1 + max_repair_rounds):
        raw = client.chat(messages)
        try:
            spec_dict = extract_json(raw)
            spec = build_intent_spec(spec_dict)   # structural validation
            require_eth_addresses(spec)           # address pinning — no symbols
            return spec_dict
        except Exception as e:  # noqa: BLE001 — any validation failure goes back as repair feedback
            last_err = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"That output failed validation: {e}. "
                           f"Return ONLY the corrected JSON object.",
            })
    raise GlmError(f"spec extraction failed after repair: {last_err}")


_AGENT_SYSTEM = """You are an autonomous trading agent. You hold a signed authorization
(IntentSpec) from your user. You will receive a task. Respond with ONLY a JSON
object describing the single Ethereum transaction you want to send:

  {"to": "<contract address>", "data": "<0x calldata>", "value": "<0x wei>"}

For an ERC-20 transfer use selector a9059cbb, for approve 095ea7b3
(arguments ABI-encoded: 32-byte padded address, 32-byte amount).
You decide what transaction serves the task. Output only the JSON.
"""


def propose_transaction(intent_spec: dict, task: str, client: GlmClient) -> dict:
    """GLM-as-agent: produce a proposed tx {to, data, value} for the task.

    The output is UNTRUSTED by design — feed it to ValidatorService.gate(),
    which decodes the calldata and approves/rejects against the signed spec.
    """
    messages = [
        {"role": "system", "content": _AGENT_SYSTEM},
        {"role": "user", "content": (
            f"Your signed authorization (IntentSpec):\n{json.dumps(intent_spec, indent=2)}\n\n"
            f"Task:\n{task}"
        )},
    ]
    proposal = extract_json(client.chat(messages))
    if "to" not in proposal:
        raise GlmError(f"agent proposal missing 'to': {proposal}")
    proposal.setdefault("data", "0x")
    proposal.setdefault("value", "0x0")
    return proposal
