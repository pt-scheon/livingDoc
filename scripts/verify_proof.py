"""Verify a LivingDoc proof packet OFFLINE: no server, no shop data, just the packet and the `cryptography` package.

    python scripts/verify_proof.py packet.json

Checks the Ed25519 signature over the claims and the Merkle root, and the validity window. It cannot tell you whether the
shop has revoked the proof (ask the shop's server for that) and it does not see any private entry. To spot-check entries,
send the shop a random nonce and verify the openings it returns (see the README, "Proof without exposure").
Exit code 0 = signature valid and not expired; 1 otherwise.
"""
import json
import sys
from datetime import date

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def _norm(o):
    """Whole-number floats become ints so 5000.0 and 5000 sign identically (JavaScript and Python print them differently)."""
    if isinstance(o, float) and o.is_integer():
        return int(o)
    if isinstance(o, dict):
        return {k: _norm(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_norm(v) for v in o]
    return o


def canon(obj) -> bytes:
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def main(path: str) -> int:
    packet = json.load(open(path, encoding="utf-8"))
    try:
        body = {k: v for k, v in packet.items() if k != "signature"}
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(packet["public_key"])).verify(bytes.fromhex(packet["signature"]), canon(body))
    except (InvalidSignature, ValueError, KeyError, TypeError):
        print("SIGNATURE INVALID: this packet was altered or was not signed by the key it names.")
        return 1
    print("SIGNATURE VALID")
    print(f"shop id: {packet['shop']}   issued: {packet['issued_on']}   valid until: {packet['valid_until']}   entries counted: {packet['entries_counted']}")
    for c in packet["claims"]:
        print(f"  claim {c['id']}: {c['op']} {c['value']} {c['unit']}")
    print("scope:", packet.get("scope_note", ""))
    if packet["valid_until"] < date.today().isoformat():
        print("EXPIRED: ask the shop for a fresh proof.")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/verify_proof.py packet.json")
    sys.exit(main(sys.argv[1]))
