"""Integrations — connect Ali OS to external services (§3, §20).

Public surface:
    catalog.as_list()                    what can be connected + form schema
    store.upsert(...)                    save credentials (encrypted)
    store.credentials(service, project)  decrypted creds for an agent
    testers.test(service, creds)         live connection check
"""
from app.integrations import catalog, crypto, store, testers  # noqa: F401
from app.integrations.crypto import CryptoError, mask, new_key  # noqa: F401

__all__ = ["catalog", "crypto", "store", "testers", "CryptoError", "mask", "new_key"]
