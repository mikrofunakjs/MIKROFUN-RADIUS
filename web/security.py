"""Shared password verification.

Historically every login path (admin, client, reseller, RADIUS) rolled its own
"try the hash, fall back to plaintext" logic. That had three problems:

  * An empty stored password authenticated an empty submitted password.
  * The fallback compared the stored *hash* against the submitted password when
    the hash failed to parse.
  * The plaintext comparison used `==`, which is not constant time.

On top of that the fallback was keyed on `check_password_hash` raising
ValueError. Werkzeug 3 returns False instead of raising, so on current versions
the legacy-plaintext migration path silently stopped working.

This module centralises the rules: recognise a hash by its scheme prefix,
otherwise treat the value as legacy plaintext, compare it in constant time, and
tell the caller to re-hash it.
"""
import hmac

from werkzeug.security import check_password_hash, generate_password_hash

# Scheme prefixes emitted by werkzeug's generate_password_hash across versions.
_HASH_PREFIXES = ('pbkdf2:', 'scrypt:', 'argon2', 'sha1$', 'sha256$', 'md5$')


def looks_hashed(stored):
    """True when `stored` is a password hash rather than legacy plaintext."""
    return isinstance(stored, str) and stored.startswith(_HASH_PREFIXES)


def verify_password(stored, provided):
    """Check `provided` against `stored`.

    Returns (is_valid, needs_rehash). `needs_rehash` is True only when the
    credential matched a legacy plaintext row, so the caller can upgrade it.
    An empty stored or provided password never authenticates.
    """
    if not stored or not provided:
        return False, False

    if not isinstance(stored, str):
        try:
            stored = stored.decode('utf-8')
        except Exception:
            return False, False

    if looks_hashed(stored):
        try:
            return bool(check_password_hash(stored, provided)), False
        except (ValueError, TypeError):
            return False, False

    # Legacy plaintext row: constant-time compare, then force an upgrade.
    ok = hmac.compare_digest(stored.strip(), str(provided).strip())
    return ok, ok


def hash_password(password):
    """Hash a password for storage."""
    return generate_password_hash(password)
