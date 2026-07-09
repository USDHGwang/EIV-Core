"""
EIV — Ethereum primitives, implemented with the Python standard library only.

EIV keeps a zero-dependency policy: the validator must be runnable and
re-runnable by anyone with a stock Python, because its trust model is
"re-verify, don't trust". That extends to the cryptography: rather than pull in
eth-utils / coincurve, this module implements the required primitives directly:

  - keccak256          : Keccak-f[1600] sponge (the pre-SHA-3 padding Ethereum uses)
  - secp256k1 ECDSA    : deterministic signing (RFC 6979) and public-key recovery
                         (ecrecover), plus address derivation
  - RLP                : recursive length prefix encoding
  - EIP-1559 tx        : typed-transaction (0x02) signing
  - ABI                : minimal encoder for the call shapes EIV needs
  - JSON-RPC           : a small urllib client

Correctness is enforced by eiv.selftest part [C]:
  - keccak256 against published test vectors,
  - private-key -> address against the canonical Anvil/Hardhat dev account,
  - sign -> recover round-trips,
  - RFC 6979 determinism.

Nothing here is performance-critical: EIV validates transactions, it does not
mine or serve high-throughput traffic.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import time as _time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Keccak-256 (Keccak-f[1600], rate 1088, original 0x01 padding — NOT SHA3-256)
# ---------------------------------------------------------------------------

_KECCAK_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

# Rotation offsets r[x][y] for lanes A[x, y] (state index x + 5y)
_KECCAK_ROT = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)

_MASK64 = (1 << 64) - 1
_RATE = 136  # bytes; 1600 - 2*256 bits


def _rotl64(x: int, s: int) -> int:
    s %= 64
    return ((x << s) | (x >> (64 - s))) & _MASK64


def _keccak_f(state: list) -> None:
    """Keccak-f[1600] permutation over 25 little-endian 64-bit lanes, in place."""
    for rnd in range(24):
        # theta
        c = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
             for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl64(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]
        # rho + pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl64(state[x + 5 * y], _KECCAK_ROT[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y])
        # iota
        state[0] ^= _KECCAK_RC[rnd]


def keccak256(data: bytes) -> bytes:
    """keccak256 as used by Ethereum (original Keccak 0x01 padding)."""
    state = [0] * 25
    # absorb
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % _RATE:
        padded.append(0x00)
    padded[-1] |= 0x80
    for off in range(0, len(padded), _RATE):
        block = padded[off : off + _RATE]
        for i in range(_RATE // 8):
            state[i] ^= int.from_bytes(block[8 * i : 8 * i + 8], "little")
        _keccak_f(state)
    # squeeze (32 bytes < rate, one block suffices)
    return b"".join(state[i].to_bytes(8, "little") for i in range(4))


def keccak256_text(text: str) -> bytes:
    return keccak256(text.encode("utf-8"))


# ---------------------------------------------------------------------------
# secp256k1
# ---------------------------------------------------------------------------

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_G = (_GX, _GY)

Point = tuple  # (x, y) affine; None is the point at infinity


def _pt_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        # doubling
        lam = (3 * x1 * x1) * pow(2 * y1, P - 2, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, P - 2, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def _pt_mul(k: int, pt) -> Point:
    k %= N
    result = None
    addend = pt
    while k:
        if k & 1:
            result = _pt_add(result, addend)
        addend = _pt_add(addend, addend)
        k >>= 1
    return result


def privkey_to_pubkey(priv: int) -> bytes:
    """Private scalar -> 64-byte uncompressed public key (x ‖ y, no 0x04 prefix)."""
    if not 1 <= priv < N:
        raise ValueError("private key out of range")
    x, y = _pt_mul(priv, _G)
    return x.to_bytes(32, "big") + y.to_bytes(32, "big")


def pubkey_to_address(pub64: bytes) -> str:
    """64-byte public key -> lowercase 0x address (keccak(pub)[12:])."""
    if len(pub64) != 64:
        raise ValueError("public key must be 64 bytes (x ‖ y)")
    return "0x" + keccak256(pub64)[12:].hex()


def privkey_to_address(priv: int) -> str:
    return pubkey_to_address(privkey_to_pubkey(priv))


def _rfc6979_k(z: int, priv: int) -> int:
    """Deterministic nonce per RFC 6979 (HMAC-SHA256), so signing needs no RNG."""
    h1 = (z % N).to_bytes(32, "big")
    x = priv.to_bytes(32, "big")
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = _hmac.new(k, v + b"\x00" + x + h1, hashlib.sha256).digest()
    v = _hmac.new(k, v, hashlib.sha256).digest()
    k = _hmac.new(k, v + b"\x01" + x + h1, hashlib.sha256).digest()
    v = _hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = _hmac.new(k, v, hashlib.sha256).digest()
        cand = int.from_bytes(v, "big")
        if 1 <= cand < N:
            return cand
        k = _hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = _hmac.new(k, v, hashlib.sha256).digest()


def ecdsa_sign(msg_hash: bytes, priv: int) -> tuple:
    """Sign a 32-byte hash. Returns (recovery_id, r, s) with low-s normalization.

    recovery_id is 0/1 (y parity of R, adjusted when s is flipped); callers add
    27 for the classic Ethereum v.
    """
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes")
    z = int.from_bytes(msg_hash, "big")
    k = _rfc6979_k(z, priv)
    while True:
        rx, ry = _pt_mul(k, _G)
        r = rx % N
        s = pow(k, N - 2, N) * (z + r * priv) % N
        if r == 0 or s == 0:  # vanishingly unlikely; re-derive k
            k = (k + 1) % N or 1
            continue
        recid = ry & 1
        if rx >= N:  # r overflow case; encode in recid per recovery spec
            recid |= 2
        if s > N // 2:
            s = N - s
            recid ^= 1
        return recid, r, s


def ecdsa_recover(msg_hash: bytes, recid: int, r: int, s: int) -> bytes:
    """Recover the 64-byte public key from a signature (ecrecover)."""
    if len(msg_hash) != 32:
        raise ValueError("msg_hash must be 32 bytes")
    if not (1 <= r < N and 1 <= s < N):
        raise ValueError("invalid signature scalars")
    if recid not in (0, 1, 2, 3):
        raise ValueError("invalid recovery id")
    x = r + (N if recid >= 2 else 0)
    if x >= P:
        raise ValueError("invalid signature (r overflow)")
    y_sq = (pow(x, 3, P) + 7) % P
    y = pow(y_sq, (P + 1) // 4, P)
    if pow(y, 2, P) != y_sq:
        raise ValueError("invalid signature (point not on curve)")
    if y & 1 != recid & 1:
        y = P - y
    rinv = pow(r, N - 2, N)
    z = int.from_bytes(msg_hash, "big")
    q = _pt_add(_pt_mul(s * rinv % N, (x, y)), _pt_mul((-z * rinv) % N, _G))
    if q is None:
        raise ValueError("invalid signature (recovered infinity)")
    return q[0].to_bytes(32, "big") + q[1].to_bytes(32, "big")


def parse_signature_hex(sig: str) -> tuple:
    """Parse a 65-byte 0x signature (r ‖ s ‖ v) -> (recid, r, s). Accepts v of 0/1/27/28."""
    raw = bytes.fromhex(sig[2:] if sig.startswith("0x") else sig)
    if len(raw) != 65:
        raise ValueError(f"signature must be 65 bytes, got {len(raw)}")
    r = int.from_bytes(raw[:32], "big")
    s = int.from_bytes(raw[32:64], "big")
    v = raw[64]
    recid = v - 27 if v >= 27 else v
    if recid not in (0, 1):
        raise ValueError(f"unsupported v value {v}")
    if s > N // 2:
        # EIP-2 low-s rule: the high-s counterpart (r, N-s, v^1) recovers the
        # same signer, so accepting it would give one authorization two valid
        # signature encodings (malleability).
        raise ValueError("high-s signature rejected (EIP-2 low-s required)")
    return recid, r, s


def signature_to_hex(recid: int, r: int, s: int) -> str:
    """(recid, r, s) -> 65-byte 0x signature with classic v = 27 + recid."""
    return "0x" + (r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([27 + (recid & 1)])).hex()


# ---------------------------------------------------------------------------
# RLP + EIP-1559 transaction signing
# ---------------------------------------------------------------------------


def _int_to_minimal(n: int) -> bytes:
    if n == 0:
        return b""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def rlp_encode(item) -> bytes:
    """RLP-encode bytes / int / list (recursively)."""
    if isinstance(item, int):
        item = _int_to_minimal(item)
    if isinstance(item, (bytes, bytearray)):
        item = bytes(item)
        if len(item) == 1 and item[0] < 0x80:
            return item
        return _rlp_len(len(item), 0x80) + item
    if isinstance(item, (list, tuple)):
        payload = b"".join(rlp_encode(x) for x in item)
        return _rlp_len(len(payload), 0xC0) + payload
    raise TypeError(f"cannot RLP-encode {type(item).__name__}")


def _rlp_len(length: int, offset: int) -> bytes:
    if length < 56:
        return bytes([offset + length])
    enc = _int_to_minimal(length)
    return bytes([offset + 55 + len(enc)]) + enc


def address_to_bytes(addr: str) -> bytes:
    raw = bytes.fromhex(addr[2:] if addr.startswith("0x") else addr)
    if len(raw) != 20:
        raise ValueError(f"address must be 20 bytes: {addr}")
    return raw


def sign_eip1559_tx(
    priv: int,
    *,
    chain_id: int,
    nonce: int,
    max_priority_fee: int,
    max_fee: int,
    gas_limit: int,
    to: str,
    value: int = 0,
    data: bytes = b"",
) -> tuple:
    """Sign a type-2 (EIP-1559) transaction. Returns (raw_tx_bytes, tx_hash_hex).

    An empty `to` signs a contract-creation transaction (RLP empty byte string).
    """
    payload = [
        chain_id,
        nonce,
        max_priority_fee,
        max_fee,
        gas_limit,
        address_to_bytes(to) if to else b"",
        value,
        data,
        [],  # access list
    ]
    sighash = keccak256(b"\x02" + rlp_encode(payload))
    recid, r, s = ecdsa_sign(sighash, priv)
    raw = b"\x02" + rlp_encode(payload + [recid & 1, r, s])
    return raw, "0x" + keccak256(raw).hex()


# ---------------------------------------------------------------------------
# Minimal ABI encoding (just what EIV's calls need)
# ---------------------------------------------------------------------------


def function_selector(signature: str) -> bytes:
    """First 4 bytes of keccak256 of the canonical signature string."""
    return keccak256_text(signature)[:4]


def _abi_word_uint(n: int) -> bytes:
    return int(n).to_bytes(32, "big")


def _abi_word_address(addr: str) -> bytes:
    return address_to_bytes(addr).rjust(32, b"\x00")


def _abi_word_bytes32(b) -> bytes:
    if isinstance(b, str):
        b = bytes.fromhex(b[2:] if b.startswith("0x") else b)
    if len(b) != 32:
        raise ValueError("bytes32 must be 32 bytes")
    return bytes(b)


def _abi_pad_dynamic(data: bytes) -> bytes:
    out = _abi_word_uint(len(data)) + data
    if len(data) % 32:
        out += b"\x00" * (32 - len(data) % 32)
    return out


def abi_encode(types: list, values: list) -> bytes:
    """Encode supported types: uint256/uint8, address, bytes32, bytes, string."""
    if len(types) != len(values):
        raise ValueError("types/values length mismatch")
    head: list = []
    tail: list = []
    head_size = 32 * len(types)
    for t, v in zip(types, values):
        if t in ("uint256", "uint8", "uint64"):
            head.append(_abi_word_uint(v))
        elif t == "address":
            head.append(_abi_word_address(v))
        elif t == "bytes32":
            head.append(_abi_word_bytes32(v))
        elif t in ("bytes", "string"):
            data = v.encode("utf-8") if isinstance(v, str) else bytes(v)
            offset = head_size + sum(len(x) for x in tail)
            head.append(_abi_word_uint(offset))
            tail.append(_abi_pad_dynamic(data))
        else:
            raise ValueError(f"unsupported ABI type {t}")
    return b"".join(head) + b"".join(tail)


def abi_call_data(signature: str, types: list, values: list) -> bytes:
    return function_selector(signature) + abi_encode(types, values)


# ---------------------------------------------------------------------------
# JSON-RPC client (urllib)
# ---------------------------------------------------------------------------


class EthRpcError(RuntimeError):
    """JSON-RPC transport failure or an error response from the node."""


_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


def retry_transport(inner, max_retries: int = 3, base_delay: float = 0.5):
    """Wrap a transport callable with retry on transient errors.

    Retries on OSError / URLError / ValueError (network-level). EthRpcError
    (RPC logic errors) are never retried. base_delay=0 for tests.
    """

    def call(method: str, params: list):
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return inner(method, params)
            except EthRpcError:
                raise
            except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
                if isinstance(e, urllib.error.HTTPError) and e.code not in _RETRYABLE_HTTP_CODES:
                    raise EthRpcError(f"RPC HTTP {e.code} calling {method}") from e
                last_error = e
                if attempt < max_retries:
                    _time.sleep(min(2 ** attempt * base_delay, 8))
        raise EthRpcError(
            f"RPC transport error calling {method} (retries exhausted): {last_error}"
        ) from last_error

    return call


def http_rpc_transport(
    rpc_url: str,
    timeout: float = 20.0,
    max_retries: int = 3,
    fallback_url: str | None = None,
):
    """Build a transport callable: (method, params) -> result.

    Retries transient errors (network failures, HTTP 429/5xx) with exponential
    backoff. If fallback_url is set, tries it after the primary is exhausted.
    RPC-level errors (malformed request, method not found) are never retried.
    """

    def _one_call(url: str):
        def call(method: str, params: list):
            body = json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
            ).encode("utf-8")
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json", "User-Agent": "eiv-validator/0.2"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if "error" in payload:
                raise EthRpcError(f"RPC error from {method}: {payload['error']}")
            return payload.get("result")
        return call

    urls = [rpc_url] + ([fallback_url] if fallback_url else [])

    def call(method: str, params: list):
        last_error: Exception | None = None
        for url in urls:
            try:
                return retry_transport(_one_call(url), max_retries)(method, params)
            except EthRpcError as e:
                last_error = e
        raise last_error  # type: ignore[misc]

    return call


def to_hex_quantity(n: int) -> str:
    return hex(n)


def from_hex_quantity(h) -> int:
    if h is None:
        return 0
    if isinstance(h, int):
        return h
    return int(h, 16)
