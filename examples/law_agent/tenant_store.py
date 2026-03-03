"""Multi-tenant persistence helpers for the Law Agent web platform."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass
class AuthSession:
    """Resolved auth session context."""

    token: str
    user_id: int
    tenant_id: int
    email: str
    tenant_name: str


class TenantStore:
    """SQLite-backed multi-tenant store for auth, docs, and settings."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def signup(self, *, company: str, email: str, password: str) -> AuthSession:
        """Create tenant + user and return an authenticated session."""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")

        company_clean = company.strip()
        email_clean = email.strip().lower()
        if not company_clean or not email_clean:
            raise ValueError("Company and email are required.")

        tenant_slug = self._slugify(company_clean)
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password=password, salt=salt)

        with self._connect() as conn:
            cur = conn.cursor()

            cur.execute("SELECT id FROM users WHERE email = ?", (email_clean,))
            if cur.fetchone() is not None:
                raise ValueError("Email already exists.")

            cur.execute(
                "INSERT INTO tenants (name, slug, created_at) VALUES (?, ?, ?)",
                (company_clean, tenant_slug, self._now()),
            )
            if cur.lastrowid is None:
                raise RuntimeError("Failed to create tenant row.")
            tenant_id = int(cur.lastrowid)

            cur.execute(
                (
                    "INSERT INTO users (tenant_id, email, password_hash, password_salt, created_at) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (tenant_id, email_clean, password_hash, salt, self._now()),
            )
            if cur.lastrowid is None:
                raise RuntimeError("Failed to create user row.")
            user_id = int(cur.lastrowid)

            token = self._create_session(conn=conn, user_id=user_id, tenant_id=tenant_id)
            conn.commit()

        return AuthSession(
            token=token,
            user_id=user_id,
            tenant_id=tenant_id,
            email=email_clean,
            tenant_name=company_clean,
        )

    def login(self, *, email: str, password: str) -> AuthSession:
        """Authenticate existing user and return session token."""
        email_clean = email.strip().lower()

        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                (
                    "SELECT u.id, u.tenant_id, u.password_hash, u.password_salt, "
                    "u.email, t.name "
                    "FROM users u JOIN tenants t ON t.id = u.tenant_id "
                    "WHERE u.email = ?"
                ),
                (email_clean,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("Invalid credentials.")

            user_id, tenant_id, stored_hash, salt, user_email, tenant_name = row
            candidate = self._hash_password(password=password, salt=str(salt))
            if candidate != stored_hash:
                raise ValueError("Invalid credentials.")

            token = self._create_session(conn=conn, user_id=int(user_id), tenant_id=int(tenant_id))
            conn.commit()

        return AuthSession(
            token=token,
            user_id=int(user_id),
            tenant_id=int(tenant_id),
            email=str(user_email),
            tenant_name=str(tenant_name),
        )

    def resolve_token(self, token: str) -> AuthSession:
        """Resolve session token to user+tenant context."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                (
                    "SELECT s.token, s.user_id, s.tenant_id, u.email, t.name, s.expires_at "
                    "FROM sessions s "
                    "JOIN users u ON u.id = s.user_id "
                    "JOIN tenants t ON t.id = s.tenant_id "
                    "WHERE s.token = ?"
                ),
                (token,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("Invalid session token.")

            token_val, user_id, tenant_id, email, tenant_name, expires_at = row
            expiry = datetime.fromisoformat(str(expires_at))
            if expiry < datetime.now(UTC):
                cur.execute("DELETE FROM sessions WHERE token = ?", (token,))
                conn.commit()
                raise ValueError("Session expired.")

        return AuthSession(
            token=str(token_val),
            user_id=int(user_id),
            tenant_id=int(tenant_id),
            email=str(email),
            tenant_name=str(tenant_name),
        )

    def upsert_playbook_json(self, *, tenant_id: int, playbook_json: str) -> None:
        """Persist tenant-specific playbook JSON."""
        with self._connect() as conn:
            conn.execute(
                (
                    "INSERT INTO tenant_settings (tenant_id, playbook_json, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(tenant_id) DO UPDATE SET playbook_json = excluded.playbook_json, "
                    "updated_at = excluded.updated_at"
                ),
                (tenant_id, playbook_json, self._now()),
            )
            conn.commit()

    def get_playbook_json(self, *, tenant_id: int) -> str | None:
        """Load tenant-specific playbook JSON if present."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT playbook_json FROM tenant_settings WHERE tenant_id = ?",
                (tenant_id,),
            )
            row = cur.fetchone()
            return str(row[0]) if row else None

    def add_document(
        self,
        *,
        tenant_id: int,
        filename: str,
        saved_path: str,
        content_type: str,
    ) -> int:
        """Register uploaded tenant reference document metadata."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                (
                    "INSERT INTO tenant_docs (tenant_id, filename, saved_path, content_type, created_at) "
                    "VALUES (?, ?, ?, ?, ?)"
                ),
                (tenant_id, filename, saved_path, content_type, self._now()),
            )
            if cur.lastrowid is None:
                raise RuntimeError("Failed to create tenant document row.")
            doc_id = int(cur.lastrowid)
            conn.commit()
            return doc_id

    def list_documents(self, *, tenant_id: int) -> list[dict[str, str | int]]:
        """List registered tenant reference documents."""
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                (
                    "SELECT id, filename, saved_path, content_type, created_at "
                    "FROM tenant_docs WHERE tenant_id = ? ORDER BY id DESC"
                ),
                (tenant_id,),
            )
            rows = cur.fetchall()

        return [
            {
                "id": int(row[0]),
                "filename": str(row[1]),
                "saved_path": str(row[2]),
                "content_type": str(row[3]),
                "created_at": str(row[4]),
            }
            for row in rows
        ]

    def list_document_paths(self, *, tenant_id: int) -> list[str]:
        """Get local file paths for all tenant documents."""
        docs = self.list_documents(tenant_id=tenant_id)
        return [str(doc["saved_path"]) for doc in docs]

    def _create_session(self, *, conn: sqlite3.Connection, user_id: int, tenant_id: int) -> str:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(days=14)
        conn.execute(
            (
                "INSERT INTO sessions (token, user_id, tenant_id, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)"
            ),
            (token, user_id, tenant_id, self._now(), expires_at.isoformat()),
        )
        return token

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tenants ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "name TEXT NOT NULL, "
                "slug TEXT NOT NULL, "
                "created_at TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "tenant_id INTEGER NOT NULL, "
                "email TEXT NOT NULL UNIQUE, "
                "password_hash TEXT NOT NULL, "
                "password_salt TEXT NOT NULL, "
                "created_at TEXT NOT NULL, "
                "FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sessions ("
                "token TEXT PRIMARY KEY, "
                "user_id INTEGER NOT NULL, "
                "tenant_id INTEGER NOT NULL, "
                "created_at TEXT NOT NULL, "
                "expires_at TEXT NOT NULL, "
                "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE, "
                "FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tenant_settings ("
                "tenant_id INTEGER PRIMARY KEY, "
                "playbook_json TEXT NOT NULL, "
                "updated_at TEXT NOT NULL, "
                "FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tenant_docs ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "tenant_id INTEGER NOT NULL, "
                "filename TEXT NOT NULL, "
                "saved_path TEXT NOT NULL, "
                "content_type TEXT NOT NULL, "
                "created_at TEXT NOT NULL, "
                "FOREIGN KEY (tenant_id) REFERENCES tenants (id) ON DELETE CASCADE"
                ")"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _hash_password(*, password: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            200_000,
        )
        return digest.hex()

    @staticmethod
    def _slugify(value: str) -> str:
        lowered = value.strip().lower()
        return "-".join(
            part for part in "".join(ch if ch.isalnum() else " " for ch in lowered).split()
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()
