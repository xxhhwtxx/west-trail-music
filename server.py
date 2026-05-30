import asyncio, json, os, re, sys, time, urllib.request, smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.header import Header
from fastapi import FastAPI, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from qqmusic_api import Client, Credential
from qqmusic_api.modules.song import SongFileInfo, SongFileType

# ── 极简路径配置 ────────────────────────────────
BASE_DIR = Path(__file__).parent
(BASE_DIR / "users").mkdir(exist_ok=True)
(BASE_DIR / "covers").mkdir(exist_ok=True)

# ── 核心模型与配置 ──────────────────────────────
QUALITY_MAP = {"128mp3": SongFileType.MP3_128, "320mp3": SongFileType.MP3_320, "flac": SongFileType.FLAC}

def load_json(p, d): return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d
def save_json(p, d): p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def get_client():
    cred_file = BASE_DIR / "credential.json"
    if cred_file.exists(): return Client(credential=Credential(**json.load(open(cred_file))))
    return Client()

# ── 用户数据存储逻辑 ────────────────────────────
def _u_dir(uid):
    d = BASE_DIR / "users" / uid; d.mkdir(exist_ok=True)
    (d / "playlists").mkdir(exist_ok=True)
    return d

def _read_pl(uid, name):
    p = _u_dir(uid) / "playlists" / f"{re.sub(r'[\\/:*?\"<>|]', '_', name)}.json"
    return load_json(p, {"name": name, "songs": []})

def _write_pl(uid, name, data):
    p = _u_dir(uid) / "playlists" / f"{re.sub(r'[\\/:*?\"<>|]', '_', name)}.json"
    save_json(p, data)

# ── FastAPI 实例 ────────────────────────────────
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/search")
async def search(keyword: str, num: int = 30):
    try:
        res = await get_client().search.search_by_type(keyword=keyword, num=num)
        songs = []
        for s in getattr(res, "song", []):
            m, sec = divmod(getattr(s, "interval", 0), 60)
            songs.append({"mid": s.mid, "name": s.name, "singer": " / ".join([i.name for i in s.singer]), "album": s.album.name, "duration": f"{m}:{sec:02d}", "interval": s.interval, "cover": s.album.cover_url()})
        return {"success": True, "songs": songs}
    except Exception as e: return {"success": False, "message": str(e)}

@app.get("/api/hot-search")
async def hot_search():
    try: return {"success": True, "keywords": [i.k for i in await get_client().search.get_hot_search()]}
    except: return {"success": False}

@app.get("/api/recommend")
async def recommend():
    try:
        res = await get_client().rank.get_rank_detail(top_id=4)
        songs = []
        for s in res.songlist:
            m, sec = divmod(getattr(s, "interval", 0), 60)
            songs.append({"mid": s.mid, "name": s.name, "singer": " / ".join([i.name for i in s.singer]), "album": s.album.name, "duration": f"{m}:{sec:02d}", "interval": s.interval, "cover": s.album.cover_url()})
        return {"success": True, "songs": songs}
    except: return {"success": False}

@app.get("/api/play-url")
async def play_url(mid: str, quality: str = "128mp3"):
    try:
        u = await get_client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=QUALITY_MAP.get(quality, SongFileType.MP3_128))
        return {"success": True, "url": f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}"} if u.data[0].purl else {"success": False}
    except: return {"success": False}

@app.get("/api/lyrics")
async def lyrics(mid: str):
    try: return {"success": True, "lyric": (await get_client().lyric.get_lyric(mid)).decrypt().lyric}
    except: return {"success": False}

@app.post("/api/register")
async def register(username: str, password: str, nickname: str, avatar: str):
    db_p = BASE_DIR / "users" / "users_db.json"
    users = load_json(db_p, {})
    if username in users: return {"success": False, "message": "已存在"}
    uid = str(int(time.time()))
    users[username] = {"id": uid, "pwd": password, "name": nickname, "avatar": avatar}
    save_json(db_p, users)
    return {"success": True, "user": users[username]}

@app.post("/api/login")
async def login(username: str, password: str):
    users = load_json(BASE_DIR / "users" / "users_db.json", {})
    if username in users and users[username]["pwd"] == password: return {"success": True, "user": users[username]}
    return {"success": False}

@app.get("/api/playlists")
async def list_pl(uid: str): return {"success": True, "playlists": sorted([f.stem for f in (_u_dir(uid) / "playlists").glob("*.json")])}

@app.post("/api/playlists")
async def create_pl(uid: str, name: str): _write_pl(uid, name, {"name": name, "songs": []}); return {"success": True}

@app.get("/api/playlists/{name}")
async def get_pl(uid: str, name: str): return {"success": True, **_read_pl(uid, name)}

@app.post("/api/playlists/{name}/add")
async def add_to_pl(uid: str, name: str, mid: str, song_name: str, singer: str, album: str, cover: str, interval: int):
    d = _read_pl(uid, name)
    if not any(s["mid"] == mid for s in d["songs"]): d["songs"].append({"mid": mid, "name": song_name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    _write_pl(uid, name, d); return {"success": True}

@app.post("/api/history")
async def add_his(uid: str, mid: str, name: str, singer: str, album: str, cover: str, interval: int):
    p = _u_dir(uid) / "history.json"
    d = load_json(p, {"recent": []})
    recent = [r for r in d["recent"] if r["mid"] != mid]
    recent.insert(0, {"mid": mid, "name": name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    d["recent"] = recent[:50]; save_json(p, d); return {"success": True}

@app.get("/api/history")
async def get_his(uid: str): return {"success": True, "recent": load_json(_u_dir(uid) / "history.json", {"recent": []})["recent"]}

@app.get("/api/favorites/check")
async def check_fav(uid: str, mid: str): return {"success": True, "is_favorite": any(s["mid"] == mid for s in _read_pl(uid, "我喜欢")["songs"])}

@app.post("/api/favorites/toggle")
async def toggle_fav(uid: str, mid: str, name: str, singer: str, album: str, cover: str, interval: int):
    d = _read_pl(uid, "我喜欢")
    is_fav = any(s["mid"] == mid for s in d["songs"])
    if is_fav: d["songs"] = [s for s in d["songs"] if s["mid"] != mid]
    else: d["songs"].append({"mid": mid, "name": song_name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    _write_pl(uid, "我喜欢", d); return {"success": True, "action": "removed" if is_fav else "added"}

# ── 邮件反馈接口 ──────────────────────────────
@app.post("/api/feedback")
async def feedback(uid: str, nickname: str, content: str):
    cred_file = BASE_DIR / "credential.json"
    if not cred_file.exists(): return {"success": False, "message": "服务端未配置邮件凭证"}

    config = json.load(open(cred_file))
    smtp_user = "2810757607@qq.com"
    smtp_pass = config.get("email_auth_code") # 授权码请填入 credential.json 的 email_auth_code 字段

    if not smtp_pass: return {"success": False, "message": "未配置邮件授权码"}

    try:
        msg = MIMEText(f"用户 ID: {uid}\n用户昵称: {nickname}\n反馈内容:\n{content}", 'plain', 'utf-8')
        msg['From'] = smtp_user
        msg['To'] = smtp_user
        msg['Subject'] = Header(f"WestTrailMusic 反馈 - 来自 {nickname}", 'utf-8')

        server = smtplib.SMTP_SSL("smtp.qq.com", 465)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [smtp_user], msg.as_string())
        server.quit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8899)))
