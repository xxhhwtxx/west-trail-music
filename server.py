import asyncio, json, os, re, sys, time, smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.header import Header
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from qqmusic_api import Client, Credential
from qqmusic_api.modules.song import SongFileInfo, SongFileType

# ── 路径 ────────────────────────────────────────
BASE = Path(__file__).parent
(BASE / "users").mkdir(exist_ok=True)
(BASE / "covers").mkdir(exist_ok=True)

# ── 工具 ────────────────────────────────────────
def load(p, d=None):
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
    except: return d

def save(p, d): p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def client():
    c = BASE / "credential.json"
    if c.exists(): return Client(credential=Credential(**json.load(open(c))))
    return Client()

Q = {"128mp3": SongFileType.MP3_128, "320mp3": SongFileType.MP3_320, "flac": SongFileType.FLAC}

def _d(uid):
    d = BASE / "users" / uid; d.mkdir(exist_ok=True)
    (d / "playlists").mkdir(exist_ok=True)
    return d

def _rpl(uid, name):
    p = _d(uid) / "playlists" / f"{re.sub(r'[\\/:*?\"<>|]','_',name)}.json"
    return load(p, {"name": name, "songs": []})

def _wpl(uid, name, data):
    p = _d(uid) / "playlists" / f"{re.sub(r'[\\/:*?\"<>|]','_',name)}.json"
    save(p, data)

def _song(s):
    m, sec = divmod(getattr(s, "interval", 0), 60)
    return {"mid": s.mid, "name": s.name, "singer": " / ".join([i.name for i in s.singer]),
            "album": getattr(s.album, "name", ""), "duration": f"{m}:{sec:02d}",
            "interval": s.interval, "cover": s.album.cover_url() if s.album else ""}

# ═══════════════════════════════════════════════════
app = FastAPI(title="WestTrailMusic")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/", response_class=HTMLResponse)
async def index():
    html = BASE / "index.html"
    return HTMLResponse(html.read_text(encoding="utf-8")) if html.exists() else HTMLResponse("<h1>WestTrailMusic API</h1>")

@app.get("/health")
async def health(): return {"status": "ok", "service": "WestTrailMusic"}

@app.get("/api/search")
async def search(keyword: str, num: int = 30):
    try:
        r = await client().search.search_by_type(keyword=keyword, num=num)
        return {"success": True, "songs": [_song(s) for s in getattr(r, "song", [])]}
    except Exception as e: return {"success": False, "message": str(e)}

@app.get("/api/hot-search")
async def hot():
    try: return {"success": True, "keywords": [i.k for i in await client().search.get_hot_search()]}
    except: return {"success": False}

@app.get("/api/recommend")
async def recommend():
    try:
        r = await client().rank.get_rank_detail(top_id=4)
        return {"success": True, "songs": [_song(s) for s in getattr(r, "songlist", [])]}
    except: return {"success": False}

@app.get("/api/play-url")
async def play_url(mid: str, quality: str = "128mp3"):
    try:
        u = await client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=Q.get(quality, SongFileType.MP3_128))
        if u and u.data and u.data[0].purl:
            return {"success": True, "url": f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}"}
    except: pass
    return {"success": False}

@app.get("/api/stream-play")
async def stream_play(mid: str, quality: str = "128mp3"):
    try:
        u = await client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=Q.get(quality, SongFileType.MP3_128))
        if not (u and u.data and u.data[0].purl): return StreamingResponse(iter([]), status_code=404)
        import requests as _r
        resp = _r.get(f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}", headers={"User-Agent":"Mozilla/5.0","Referer":"https://y.qq.com/"}, stream=True, timeout=30)
        return StreamingResponse(resp.iter_content(chunk_size=65536), status_code=200, media_type="audio/mpeg")
    except: return StreamingResponse(iter([]), status_code=404)

@app.get("/api/lyrics")
async def lyrics(mid: str):
    try: return {"success": True, "lyric": (await client().lyric.get_lyric(mid)).decrypt().lyric}
    except: return {"success": False}

# ── 账户 ────────────────────────────────────────
@app.post("/api/register")
async def register(username: str, password: str, nickname: str, avatar: str = ""):
    db = load(BASE / "users" / "users_db.json", {})
    if username in db: return {"success": False, "message": "用户名已存在"}
    uid = str(int(time.time()))
    db[username] = {"id": uid, "pwd": password, "name": nickname, "avatar": avatar}
    save(BASE / "users" / "users_db.json", db)
    return {"success": True, "user": db[username]}

@app.post("/api/login")
async def login(username: str, password: str):
    db = load(BASE / "users" / "users_db.json", {})
    u = db.get(username)
    if u and u["pwd"] == password: return {"success": True, "user": u}
    return {"success": False}

# ── 播放列表 ────────────────────────────────────
@app.get("/api/playlists")
async def pl_list(uid: str = "guest"):
    return {"success": True, "playlists": sorted(f.stem for f in (_d(uid) / "playlists").glob("*.json"))}

@app.post("/api/playlists")
async def pl_create(uid: str, name: str):
    _wpl(uid, name, {"name": name, "songs": []}); return {"success": True}

@app.get("/api/playlists/{name}")
async def pl_get(uid: str, name: str):
    return {"success": True, **_rpl(uid, name)}

@app.post("/api/playlists/{name}/add")
async def pl_add(uid: str, name: str, mid: str, song_name: str, singer: str = "", album: str = "", cover: str = "", interval: int = 0):
    d = _rpl(uid, name)
    if not any(s["mid"] == mid for s in d["songs"]):
        d["songs"].append({"mid": mid, "name": song_name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    _wpl(uid, name, d); return {"success": True}

@app.post("/api/playlists/{name}/remove")
async def pl_remove(uid: str, name: str, mid: str):
    d = _rpl(uid, name)
    d["songs"] = [s for s in d["songs"] if s["mid"] != mid]
    _wpl(uid, name, d); return {"success": True}

# ── 收藏 ────────────────────────────────────────
@app.get("/api/favorites/check")
async def fav_check(uid: str, mid: str):
    return {"success": True, "is_favorite": any(s["mid"] == mid for s in _rpl(uid, "我喜欢")["songs"])}

@app.post("/api/favorites/toggle")
async def fav_toggle(uid: str, mid: str, name: str, singer: str = "", album: str = "", cover: str = "", interval: int = 0):
    d = _rpl(uid, "我喜欢")
    is_fav = any(s["mid"] == mid for s in d["songs"])
    if is_fav: d["songs"] = [s for s in d["songs"] if s["mid"] != mid]
    else: d["songs"].append({"mid": mid, "name": name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    _wpl(uid, "我喜欢", d); return {"success": True, "action": "removed" if is_fav else "added"}

# ── 历史 ────────────────────────────────────────
@app.post("/api/history")
async def his_add(uid: str = "guest", mid: str = "", name: str = "", singer: str = "", album: str = "", cover: str = "", interval: int = 0):
    p = _d(uid) / "history.json"
    d = load(p, {"recent": []})
    d["recent"] = [r for r in d["recent"] if r["mid"] != mid]
    d["recent"].insert(0, {"mid": mid, "name": name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    d["recent"] = d["recent"][:50]; save(p, d); return {"success": True}

@app.get("/api/history")
async def his_get(uid: str = "guest"):
    return {"success": True, "recent": load(_d(uid) / "history.json", {"recent": []})["recent"]}

# ── 反馈 ────────────────────────────────────────
APP_EMAIL = "2810757607@qq.com"
APP_EMAIL_KEY = os.environ.get("EMAIL_AUTH_CODE", "iypidfdqejnidgag")

# ── 封面缓存 ────────────────────────────────────
@app.get("/api/covers/cache/{mid}")
async def cover_cache(mid: str, url: str = ""):
    try:
        if not url: return {"success": False}
        p = BASE / "covers" / f"{mid}.jpg"
        if not p.exists():
            import urllib.request as _ur
            req = _ur.Request(url, headers={"Referer":"https://y.qq.com/","User-Agent":"Mozilla/5.0"})
            with _ur.urlopen(req, timeout=8) as r: p.write_bytes(r.read())
        return {"success": True}
    except: return {"success": False}

# ── 下载 ────────────────────────────────────────
@app.get("/api/download")
async def download(mid: str, quality: str = "320mp3", name: str = "", singer: str = "", album: str = "", cover: str = ""):
    try:
        u = await client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=Q.get(quality, SongFileType.MP3_320))
        if not (u and u.data and u.data[0].purl): return {"success": False, "message": "无法获取下载链接"}
        url = f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}"
        ext = {"128mp3":"mp3","320mp3":"mp3","flac":"flac"}.get(quality, "mp3")
        safe = f"{singer} - {name}" if singer and name else mid
        safe = "".join(c for c in safe if c not in r'\/:*?"<>|')
        fp = BASE / "downloads" / f"{safe}.{ext}"
        (BASE / "downloads").mkdir(exist_ok=True)
        await asyncio.to_thread(lambda: __import__('urllib.request').request.urlretrieve(url, str(fp)))
        return {"success": True, "message": f"下载完成: {fp.name}"}
    except Exception as e: return {"success": False, "message": str(e)}

@app.post("/api/feedback")
async def feedback(uid: str = "", nickname: str = "", content: str = ""):
    try:
        msg = MIMEText(f"用户 ID: {uid}\n昵称: {nickname}\n\n{content}", "plain", "utf-8")
        msg["From"] = APP_EMAIL
        msg["To"] = APP_EMAIL
        msg["Subject"] = Header(f"WestTrail 反馈 - {nickname}", "utf-8")
        with smtplib.SMTP_SSL("smtp.qq.com", 465) as s:
            s.login(APP_EMAIL, APP_EMAIL_KEY)
            s.sendmail(APP_EMAIL, [APP_EMAIL], msg.as_string())
        return {"success": True}
    except Exception as e: return {"success": False, "message": str(e)}

# ── 本地文件管理 ────────────────────────────────
DOWNLOADS = BASE / "downloads"; DOWNLOADS.mkdir(exist_ok=True)

@app.get("/api/downloads")
async def list_downloads():
    files = []
    for f in sorted(DOWNLOADS.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".mp3", ".flac", ".ogg", ".m4a"):
            sz = f.stat().st_size / (1024 * 1024)
            mt = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
            files.append({"filename": f.name, "size_mb": round(sz, 2), "time": mt})
    return {"success": True, "files": files}

@app.get("/api/delete-download")
async def delete_download(filename: str):
    fp = (DOWNLOADS / filename).resolve()
    if not str(fp).startswith(str(DOWNLOADS.resolve())): return {"success": False}
    if fp.exists(): fp.unlink()
    return {"success": True}

@app.get("/api/open-folder")
async def open_folder():
    if sys.platform == 'win32': os.startfile(str(DOWNLOADS))
    return {"success": True}

# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8899)))
