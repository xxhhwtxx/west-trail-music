import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "westtrail.db"

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        # 用户表
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            nickname TEXT,
            avatar TEXT
        )''')
        # 歌单表
        c.execute('''CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT,
            name TEXT,
            UNIQUE(uid, name)
        )''')
        # 歌单里的歌曲
        c.execute('''CREATE TABLE IF NOT EXISTS playlist_songs (
            playlist_id INTEGER,
            mid TEXT,
            name TEXT,
            singer TEXT,
            album TEXT,
            cover TEXT,
            interval INTEGER,
            PRIMARY KEY(playlist_id, mid)
        )''')
        # 播放历史记录
        c.execute('''CREATE TABLE IF NOT EXISTS history (
            uid TEXT,
            mid TEXT,
            name TEXT,
            singer TEXT,
            album TEXT,
            cover TEXT,
            interval INTEGER,
            added_at REAL,
            UNIQUE(uid, mid)
        )''')
        conn.commit()

init_db()

# DB 辅助操作
def get_user_by_username(username):
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

def create_user(uid, username, password, nickname, avatar):
    with get_db() as db:
        try:
            db.execute("INSERT INTO users (id, username, password, nickname, avatar) VALUES (?, ?, ?, ?, ?)",
                       (uid, username, password, nickname, avatar))
            db.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def get_playlists(uid):
    with get_db() as db:
        return [row["name"] for row in db.execute("SELECT name FROM playlists WHERE uid = ? ORDER BY id", (uid,))]

def ensure_playlist_exists(uid, name):
    with get_db() as db:
        try:
            db.execute("INSERT INTO playlists (uid, name) VALUES (?, ?)", (uid, name))
            db.commit()
        except sqlite3.IntegrityError:
            pass
        return db.execute("SELECT id FROM playlists WHERE uid = ? AND name = ?", (uid, name)).fetchone()["id"]

def get_playlist_songs(uid, name):
    with get_db() as db:
        pid_row = db.execute("SELECT id FROM playlists WHERE uid = ? AND name = ?", (uid, name)).fetchone()
        if not pid_row: return {"name": name, "songs": []}
        songs = db.execute("SELECT mid, name, singer, album, cover, interval FROM playlist_songs WHERE playlist_id = ?", (pid_row["id"],)).fetchall()
        return {"name": name, "songs": [dict(s) for s in songs]}

def add_song_to_playlist(uid, name, song):
    pid = ensure_playlist_exists(uid, name)
    with get_db() as db:
        try:
            db.execute("INSERT INTO playlist_songs (playlist_id, mid, name, singer, album, cover, interval) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (pid, song["mid"], song["name"], song["singer"], song["album"], song["cover"], song["interval"]))
            db.commit()
        except sqlite3.IntegrityError:
            pass # 已经存在

def remove_song_from_playlist(uid, name, mid):
    with get_db() as db:
        pid_row = db.execute("SELECT id FROM playlists WHERE uid = ? AND name = ?", (uid, name)).fetchone()
        if pid_row:
            db.execute("DELETE FROM playlist_songs WHERE playlist_id = ? AND mid = ?", (pid_row["id"], mid))
            db.commit()

def rename_playlist(uid, old_name, new_name):
    with get_db() as db:
        db.execute("UPDATE playlists SET name = ? WHERE uid = ? AND name = ?", (new_name, uid, old_name))
        db.commit()

def delete_playlist(uid, name):
    with get_db() as db:
        pid_row = db.execute("SELECT id FROM playlists WHERE uid = ? AND name = ?", (uid, name)).fetchone()
        if pid_row:
            db.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", (pid_row["id"],))
            db.execute("DELETE FROM playlists WHERE id = ?", (pid_row["id"],))
            db.commit()

def add_history(uid, song):
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO history (uid, mid, name, singer, album, cover, interval, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (uid, song["mid"], song["name"], song["singer"], song["album"], song["cover"], song["interval"], time.time()))
        # 限制最多50条
        db.execute("DELETE FROM history WHERE uid = ? AND mid NOT IN (SELECT mid FROM history WHERE uid = ? ORDER BY added_at DESC LIMIT 50)", (uid, uid))
        db.commit()

def get_history(uid):
    with get_db() as db:
        songs = db.execute("SELECT mid, name, singer, album, cover, interval FROM history WHERE uid = ? ORDER BY added_at DESC", (uid,)).fetchall()
        return [dict(s) for s in songs]
