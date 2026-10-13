"""SQLite persistence. Mutations use BEGIN IMMEDIATE; no process-global connection."""
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return secrets.token_hex(16)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def packed(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO schema_version VALUES(1);
                CREATE TABLE IF NOT EXISTS users(
                    id TEXT PRIMARY KEY, openid TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL, profile TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS groups(
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES users(id),
                    name TEXT NOT NULL, invite_hash TEXT UNIQUE NOT NULL, settings TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members(
                    group_id TEXT REFERENCES groups(id), user_id TEXT REFERENCES users(id),
                    role TEXT NOT NULL CHECK(role IN ('admin','member')), PRIMARY KEY(group_id,user_id));
                CREATE TABLE IF NOT EXISTS entities(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL, owner TEXT NOT NULL,
                    body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS entity_scope ON entities(kind,scope);
                CREATE INDEX IF NOT EXISTS entity_owner ON entities(kind,owner);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL,
                    owner TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS event_scope ON events(scope,seq);
            """)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        return {**json.loads(row["body"]), "id": row["id"], "group_id": row["scope"],
                "owner_id": row["owner"], "version": row["version"], "created_at": row["created"], "updated_at": row["updated"]}

    def get(self, db, key, kind=None):
        row = db.execute("SELECT * FROM entities WHERE id=?", (key,)).fetchone()
        if row is None or (kind and row["kind"] != kind):
            raise HTTPException(404, "Record not found")
        return self.decode(row)

    def items(self, db, kind, scope=None, owner=None):
        sql, args = "SELECT * FROM entities WHERE kind=?", [kind]
        if scope is not None:
            sql += " AND scope=?"
            args.append(scope)
        if owner is not None:
            sql += " AND owner=?"
            args.append(owner)
        return [self.decode(row) for row in db.execute(sql + " ORDER BY created DESC", args)]

    def put(self, db, kind, scope, owner, body, key=None, expected=None):
        key = key or uid()
        old = db.execute("SELECT version,kind,scope,owner FROM entities WHERE id=?", (key,)).fetchone()
        if old and (old["kind"], old["scope"], old["owner"]) != (kind, scope, owner):
            raise HTTPException(409, "Record identity collision")
        if expected is not None and (old is None or old["version"] != expected):
            raise HTTPException(409, "Data changed; refresh and try again")
        body = {k: v for k, v in body.items() if k not in {"id", "group_id", "owner_id", "version", "created_at", "updated_at"}}
        stamp = now()
        db.execute("""INSERT INTO entities(id,kind,scope,owner,body,created,updated) VALUES(?,?,?,?,?,?,?)
                      ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=entities.version+1,updated=excluded.updated""",
                   (key, kind, scope, owner, packed(body), stamp, stamp))
        return self.get(db, key)

    def member(self, db, group, user, admin=False):
        row = db.execute("SELECT role FROM members WHERE group_id=? AND user_id=?", (group, user)).fetchone()
        if not row or (admin and row["role"] != "admin"):
            raise HTTPException(403, "Group access denied")
        return row["role"]

    def emit(self, db, scope, owner, kind, body):
        return db.execute("INSERT INTO events(scope,owner,kind,body,created) VALUES(?,?,?,?,?)",
                          (scope, owner, kind, packed(body), now())).lastrowid

    def events(self, db, scope, after=0):
        return [{"id": row["seq"], "type": row["kind"], "data": json.loads(row["body"])}
                for row in db.execute("SELECT * FROM events WHERE scope=? AND seq>? ORDER BY seq LIMIT 100", (scope, after))]
