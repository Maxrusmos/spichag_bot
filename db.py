import os
import sqlite3
from contextlib import closing

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "bot.db"))

DEFAULTS = dict(base_weeks=8, extra_weeks=0, days="0,2,4", morning="08:00", evening=1,
                tz="Europe/Moscow", start_date=None, legs="both", start_pos="stand", active=0)


def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with closing(conn()) as c, c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, chat_id INTEGER,
            base_weeks INTEGER, extra_weeks INTEGER, days TEXT, morning TEXT, evening INTEGER,
            tz TEXT, start_date TEXT, legs TEXT, start_pos TEXT, active INTEGER);
        CREATE TABLE IF NOT EXISTS workouts(
            user_id INTEGER, date TEXT, status TEXT, reminded INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, date));
        CREATE TABLE IF NOT EXISTS tests(
            user_id INTEGER, date TEXT, key TEXT, value TEXT, PRIMARY KEY(user_id, date, key));
        CREATE TABLE IF NOT EXISTS media(key TEXT PRIMARY KEY, file_id TEXT);
        """)


def get_user(uid):
    with closing(conn()) as c:
        r = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return dict(r) if r else None


def create_user(uid, chat_id):
    with closing(conn()) as c, c:
        c.execute(f"INSERT OR IGNORE INTO users(user_id, chat_id, {', '.join(DEFAULTS)}) "
                  f"VALUES(?, ?, {', '.join('?' * len(DEFAULTS))})", (uid, chat_id, *DEFAULTS.values()))
    return get_user(uid)


def update_user(uid, **kw):
    with closing(conn()) as c, c:
        c.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in kw)} WHERE user_id=?", (*kw.values(), uid))


def all_users():
    with closing(conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM users WHERE active=1")]


def get_workout(uid, date):
    with closing(conn()) as c:
        r = c.execute("SELECT * FROM workouts WHERE user_id=? AND date=?", (uid, date)).fetchone()
        return dict(r) if r else None


def set_workout(uid, date, status=None, reminded=None):
    with closing(conn()) as c, c:
        c.execute("INSERT OR IGNORE INTO workouts(user_id, date, status) VALUES(?, ?, 'sent')", (uid, date))
        if status:
            c.execute("UPDATE workouts SET status=? WHERE user_id=? AND date=?", (status, uid, date))
        if reminded is not None:
            c.execute("UPDATE workouts SET reminded=? WHERE user_id=? AND date=?", (reminded, uid, date))


def workouts(uid):
    with closing(conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM workouts WHERE user_id=? ORDER BY date", (uid,))]


def reset_progress(uid):
    with closing(conn()) as c, c:
        c.execute("DELETE FROM workouts WHERE user_id=?", (uid,))
        c.execute("DELETE FROM tests WHERE user_id=?", (uid,))


def save_test(uid, date, key, value):
    with closing(conn()) as c, c:
        c.execute("INSERT OR REPLACE INTO tests VALUES(?, ?, ?, ?)", (uid, date, key, value))


def tests(uid):
    with closing(conn()) as c:
        return [dict(r) for r in c.execute("SELECT * FROM tests WHERE user_id=? ORDER BY date", (uid,))]


def media_get(key):
    with closing(conn()) as c:
        r = c.execute("SELECT file_id FROM media WHERE key=?", (key,)).fetchone()
        return r[0] if r else None


def media_set(key, file_id):
    with closing(conn()) as c, c:
        c.execute("INSERT OR REPLACE INTO media VALUES(?, ?)", (key, file_id))
