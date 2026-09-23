"""User accounts -- this app's own login/auth infrastructure (see also
schema/constraints.cypher's User constraints), not part of CLAUDE.md's
domain schema. Stored in the same graph as everything else rather than
standing up a second datastore for one small table.

Passwords are hashed with bcrypt (a deliberately slow, salted KDF) --
never stored, logged, or compared in plain text.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import bcrypt


def new_user_id() -> str:
    return f"user-{uuid.uuid4().hex[:8]}"


def _normalize_email(email: str) -> str:
    """Email is case-insensitive by convention -- without this, 'Jane@x.com'
    and 'jane@x.com' would pass the database's uniqueness constraint as
    two different accounts, defeating the point of it."""
    return email.strip().lower()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password_hash(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_user(session, email: str, name: str, password: str) -> str:
    """Raises ValueError if the email is already registered -- checked
    explicitly rather than relying on the database's own uniqueness
    constraint, so callers (the CLI, any future admin route) get a clear
    message instead of a raw Cypher error."""
    email = _normalize_email(email)
    if get_user_by_email(session, email) is not None:
        raise ValueError(f"a user with email '{email}' already exists")

    user_id = new_user_id()
    session.run(
        """
        CREATE (u:User {
            id: $id, email: $email, name: $name,
            password_hash: $password_hash, created_at: $created_at
        })
        """,
        id=user_id,
        email=email,
        name=name,
        password_hash=hash_password(password),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return user_id


def get_user_by_email(session, email: str) -> dict | None:
    result = session.run(
        """
        MATCH (u:User {email: $email})
        RETURN u.id AS id, u.email AS email, u.name AS name, u.password_hash AS password_hash
        """,
        email=_normalize_email(email),
    ).single()
    return dict(result) if result else None


def get_user_by_id(session, user_id: str) -> dict | None:
    """No password_hash in this one -- every caller of get_user_by_id is
    resolving an already-authenticated session's user_id back into a
    profile to show/attribute, never re-checking a password."""
    result = session.run(
        "MATCH (u:User {id: $id}) RETURN u.id AS id, u.email AS email, u.name AS name",
        id=user_id,
    ).single()
    return dict(result) if result else None


def verify_password(session, email: str, password: str) -> dict | None:
    """Returns the user's public profile (id/email/name, no hash) if
    email+password match, else None -- deliberately the same shape
    whether the email doesn't exist or the password is wrong, so a login
    form response can't be used to enumerate which emails are registered."""
    user = get_user_by_email(session, email)
    if user is None:
        return None
    if not verify_password_hash(password, user["password_hash"]):
        return None
    return {"id": user["id"], "email": user["email"], "name": user["name"]}
