import json
import hashlib

import paramiko


def _spec_hash(user: str, pubkey_path: str) -> str:
    """Stable hash that captures the cloud-init spec identity.

    Matches the original behavior: the hash is over (user, pubkey contents).
    """
    with open(pubkey_path, encoding="utf-8") as fh:
        pub = fh.read().strip()
    blob = json.dumps({"user": user, "pub": pub}, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def _load_pkey(path: str):
    """Try common private key formats, raising if none match.

    Keep the order and exceptions identical to the original implementation.
    """
    for key_cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
        try:
            return key_cls.from_private_key_file(path)
        except Exception as e:
            print("Error loading _pkey", e)
            continue
    raise RuntimeError(f"Could not load the private key: {path}")
