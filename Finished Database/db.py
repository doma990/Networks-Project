"""SQLite storage for the messaging server.

This module knows nothing about sockets or protocols. It only saves and
fetches rows. The core calls it; adapters never do.
"""
import hashlib
import hmac
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at    REAL NOT NULL
);

-- seq is assigned by the server only. AUTOINCREMENT means a number is never reused.
-- id is the sender's UUID. UNIQUE makes the database itself reject duplicates.
-- recipient is a username, or a room name for group chat.
CREATE TABLE IF NOT EXISTS messages (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    id        TEXT NOT NULL UNIQUE,
    sender    TEXT NOT NULL,
    recipient TEXT NOT NULL,
    text      TEXT NOT NULL,
    ts        REAL NOT NULL,
    stored_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient);
CREATE INDEX IF NOT EXISTS idx_messages_sender    ON messages(sender);

CREATE TABLE IF NOT EXISTS rooms (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS room_members (
    room     TEXT NOT NULL REFERENCES rooms(name),
    username TEXT NOT NULL,
    PRIMARY KEY (room, username)
);

-- One row per (message, user) once that user has ACKed it.
CREATE TABLE IF NOT EXISTS deliveries (
    seq          INTEGER NOT NULL REFERENCES messages(seq),
    username     TEXT NOT NULL,
    delivered_at REAL NOT NULL,
    PRIMARY KEY (seq, username)
);
"""

MESSAGE_COLUMNS = "seq, id, sender, recipient, text, ts"


class Database:
    def __init__(self, path="messages.db"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self):
        self.conn.close()

    # ---------- messages ----------

    def save_message(self, msg_id, sender, recipient, text, ts):
        """Store a message. Returns (seq, is_new).

        If msg_id was already stored (a retry), nothing is written and the
        original seq is returned with is_new=False, so the core can just re-ACK.
        """
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO messages (id, sender, recipient, text, ts, stored_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (msg_id, sender, recipient, text, ts, time.time()),
            )
            if cur.rowcount == 1:
                return cur.lastrowid, True
        row = self.conn.execute("SELECT seq FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return row["seq"], False

    def message_exists(self, msg_id):
        row = self.conn.execute("SELECT 1 FROM messages WHERE id = ?", (msg_id,)).fetchone()
        return row is not None

    def fetch_after(self, username, last_seq):
        """Everything after last_seq that involves this user, oldest first.

        Involves = they sent it, it was sent to them, or it went to a room they are in.
        """
        rows = self.conn.execute(
            f"SELECT {MESSAGE_COLUMNS} FROM messages "
            "WHERE seq > ? AND (sender = ? OR recipient = ? "
            "     OR recipient IN (SELECT room FROM room_members WHERE username = ?)) "
            "ORDER BY seq",
            (last_seq, username, username, username),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_delivered(self, username, seq):
        """Record that username ACKed seq. Safe to call twice."""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO deliveries (seq, username, delivered_at) VALUES (?, ?, ?)",
                (seq, username, time.time()),
            )

    # ---------- rooms (group chat) ----------

    def create_room(self, name):
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO rooms (name) VALUES (?)", (name,))

    def add_member(self, room, username):
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO room_members (room, username) VALUES (?, ?)",
                (room, username),
            )

    def recipients_of(self, recipient):
        """Usernames a message to `recipient` must reach: the room's members, or just that user."""
        is_room = self.conn.execute("SELECT 1 FROM rooms WHERE name = ?", (recipient,)).fetchone()
        if not is_room:
            return [recipient]
        rows = self.conn.execute(
            "SELECT username FROM room_members WHERE room = ?", (recipient,)
        ).fetchall()
        return [r["username"] for r in rows]

    # ---------- users (registration) ----------

    def create_user(self, username, password):
        """Returns True if created, False if the username is taken."""
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
        stored = salt.hex() + ":" + digest.hex()
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, stored, time.time()),
            )
        return cur.rowcount == 1

    def check_user(self, username, password):
        row = self.conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return False
        salt_hex, digest_hex = row["password_hash"].split(":")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100_000)
        return hmac.compare_digest(digest.hex(), digest_hex)