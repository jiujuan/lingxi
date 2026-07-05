"""Re-encrypt stored provider secrets: migrate enc:v1 -> enc:v2 and/or rotate keys.

Usage
-----
Format migration (legacy enc:v1 -> AES-GCM enc:v2), same key::

    python -m server.scripts.reencrypt_secrets

Key rotation (decrypt with the OLD key, re-encrypt with the CURRENT key)::

    OLD_SECRET_ENCRYPTION_KEY=<old> SECRET_ENCRYPTION_KEY=<new> \
        python -m server.scripts.reencrypt_secrets

Steps for a rotation:
  1. Deploy the new SECRET_ENCRYPTION_KEY while keeping the old one available.
  2. Run this script with OLD_SECRET_ENCRYPTION_KEY set to the previous value.
  3. Once it reports success, remove OLD_SECRET_ENCRYPTION_KEY.

The script is idempotent: rows already readable with the current key are simply
rewritten as enc:v2.
"""

import os

from sqlalchemy import select

from server.app.core.secrets import decrypt_secret, encrypt_secret
from server.app.db.session import SessionLocal
from server.app.models.model_config import ModelProvider


def reencrypt_all() -> dict:
    old_key = os.getenv("OLD_SECRET_ENCRYPTION_KEY") or None
    migrated = 0
    skipped = 0
    with SessionLocal() as session:
        providers = session.scalars(
            select(ModelProvider).where(ModelProvider.encrypted_api_key.is_not(None))
        ).all()
        for provider in providers:
            if not provider.encrypted_api_key:
                skipped += 1
                continue
            plaintext = decrypt_secret(provider.encrypted_api_key, secret_key=old_key)
            provider.encrypted_api_key = encrypt_secret(plaintext)
            migrated += 1
        session.commit()
    return {"migrated": migrated, "skipped": skipped}


if __name__ == "__main__":
    result = reencrypt_all()
    print(f"re-encrypted {result['migrated']} provider secret(s); skipped {result['skipped']}")
