import asyncio, json, os, re, sys, time, smtplib
from pathlib import Path
from urllib.parse import quote
from email.mime.text import MIMEText
from email.header import Header
from fastapi import FastAPI, Query, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from qqmusic_api import Client, Credential
from qqmusic_api.modules.song import SongFileInfo, SongFileType
from qqmusic_api.modules.login import QRLoginType
import base64, io

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
    env_cred = os.environ.get("CREDENTIAL_JSON", "")
    if env_cred: return Client(credential=Credential(**json.loads(env_cred)))
    return Client()

Q = {"128mp3": SongFileType.MP3_128, "320mp3": SongFileType.MP3_320, "ogg": SongFileType.MP3_320, "flac": SongFileType.FLAC}

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
    try:
        m, sec = divmod(getattr(s, "interval", 0), 60)
        singer_name = " / ".join([i.name for i in getattr(s, "singer", [])]) if hasattr(s, "singer") else "未知歌手"
        album_name = getattr(s.album, "name", "未知专辑") if hasattr(s, "album") else "未知专辑"
        cover = ""
        if hasattr(s, "album") and s.album:
            try: cover = s.album.cover_url()
            except: pass
        return {"mid": s.mid, "name": s.name, "singer": singer_name,
                "album": album_name, "duration": f"{m}:{sec:02d}",
                "interval": s.interval, "cover": cover}
    except Exception as e:
        print(f"[数据转换错误] {e}")
        return {"mid": getattr(s, "mid", ""), "name": getattr(s, "name", "未知歌曲"), "singer": "未知", "album": "", "duration": "0:00", "interval": 0, "cover": ""}

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

@app.get("/api/search-suggest")
async def search_suggest(keyword: str):
    try:
        # 获取建议
        c = client()
        r = await c.search.get_search_suggestion(keyword=keyword)
        res = []

        # 深度探索返回结构
        def process_items(category, type_label):
            items = getattr(r, category, [])
            if not items: return
            item_list = getattr(items, 'itemlist', items) if not isinstance(items, list) else items
            for item in item_list:
                name = getattr(item, 'name', '')
                if not name: continue
                singer = getattr(item, 'singer', '')
                res.append({
                    "type": type_label,
                    "text": f"{name} - {singer}" if singer else name,
                    "val": name
                })

        process_items('song', '单曲')
        process_items('singer', '歌手')
        process_items('album', '专辑')

        if not res:
             # 降级尝试直接请求
             import requests
             url = f"https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?key={keyword}"
             resp = requests.get(url, timeout=3).json()
             data = resp.get('data', {})
             for cat in ['song', 'singer', 'album']:
                 for item in data.get(cat, {}).get('itemlist', []):
                     name = item.get('name')
                     res.append({
                         "type": {"song":"单曲","singer":"歌手","album":"专辑"}[cat],
                         "text": f"{name} - {item.get('singer')}" if item.get('singer') else name,
                         "val": name
                     })
        return {"success": True, "data": res[:10]}
    except Exception as e:
        print(f"[搜索建议请求异常] {e}")
        return {"success": False}

@app.get("/api/credential/status")
async def credential_status():
    """查看凭证状态"""
    c = BASE / "credential.json"
    if not c.exists():
        return {"success": True, "exists": False, "message": "未配置凭证"}
    cred = Credential(**json.load(open(c)))
    return {
        "success": True,
        "exists": True,
        "expired": cred.is_expired(),
        "login_type": cred.login_type,
        "musicid": cred.musicid,
    }

@app.post("/api/credential/set")
async def credential_set(cred_json: str = ""):
    """直接设置凭证 JSON"""
    if not cred_json:
        return {"success": False, "message": "缺少凭证 JSON"}
    try:
        cred = Credential(**json.loads(cred_json))
        save(BASE / "credential.json", cred.model_dump(by_alias=True))
        return {"success": True, "musicid": cred.musicid}
    except Exception as e:
        return {"success": False, "message": str(e)}

# ── 二维码登录 ────────────────────────────────
_qr_store = {}  # identifier -> QR object

@app.get("/api/login/qrcode")
async def login_qrcode(type: str = "qq"):
    """获取登录二维码 (qq/wx)"""
    lt = QRLoginType.QQ if type == "qq" else QRLoginType.WX
    try:
        qr = await client().login.get_qrcode(lt)
        buf = io.BytesIO()
        qr.save(buf)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
        _qr_store[qr.identifier] = qr
        return {
            "success": True,
            "id": qr.identifier,
            "image": f"data:image/png;base64,{img_b64}",
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/login/qrcode/check")
async def login_qrcode_check(id: str):
    """检查扫码状态"""
    qr = _qr_store.get(id)
    if not qr:
        return {"success": False, "message": "二维码已过期或不存在"}
    try:
        result = await client().login.check_qrcode(qr)
        if result.is_done and result.credential:
            save(BASE / "credential.json", result.credential.model_dump(by_alias=True))
            _qr_store.pop(id, None)
            return {"success": True, "done": True, "message": "登录成功"}
        return {"success": True, "done": False, "event": result.event.value}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """扫码登录页面"""
    return HTMLResponse("""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>登录 WestTrail</title>
<style>body{background:#121212;color:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column}
#qr{width:220px;height:220px;border-radius:12px;background:rgba(255,255,255,.05);display:flex;align-items:center;justify-content:center;margin:20px 0}
#qr img{width:200px;height:200px;border-radius:8px}
#status{margin-top:12px;font-size:15px;color:rgba(255,255,255,.7)}
#status.success{color:#4caf50}
button{background:#fa586a;color:#fff;border:none;padding:10px 24px;border-radius:20px;font-size:14px;cursor:pointer;margin-top:16px}
</style></head><body>
<h2>WestTrail Music</h2><p style="color:#999;font-size:13px">请用 QQ音乐/QQ/微信 扫码登录</p>
<div id="qr"><span id="loading" style="color:#666">加载中…</span></div>
<div id="status">等待扫码…</div>
<button onclick="newCode()">换一张</button>
<script>
let qrId='',timer=null;
async function load(){
  document.getElementById('loading').style.display='block';
  const r=await fetch('/api/login/qrcode?type=qq'),d=await r.json();
  if(d.success){
    qrId=d.id;
    document.getElementById('qr').innerHTML='<img src="'+d.image+'">';
    document.getElementById('loading').style.display='none';
    startCheck();
  }else{
    document.getElementById('status').textContent='获取失败: '+d.message;
  }
}
function newCode(){clearInterval(timer);load();}
async function check(){
  if(!qrId)return;
  const r=await fetch('/api/login/qrcode/check?id='+qrId),d=await r.json();
  if(d.done){
    document.getElementById('status').textContent='✅ '+d.message;
    document.getElementById('status').className='success';
    clearInterval(timer);
  }else if(d.event)document.getElementById('status').textContent='状态: '+d.event;
}
function startCheck(){clearInterval(timer);timer=setInterval(check,2000);}
load();
</script></body></html>""")

@app.post("/api/credential/refresh")
async def credential_refresh():
    """刷新凭证 (延长有效期)"""
    c = BASE / "credential.json"
    if not c.exists():
        return {"success": False, "message": "没有可刷新的凭证"}
    try:
        cred = Credential(**json.load(open(c)))
        new_cred = await client().login.refresh_credential(cred)
        save(c, new_cred.model_dump(by_alias=True))
        return {"success": True, "message": "凭证已刷新", "expired": new_cred.is_expired()}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/login/cookie")
async def login_cookie(cookie: str):
    """通过 Cookie 登录并保存凭证"""
    try:
        cred = Credential(cookie=cookie)
        save(BASE / "credential.json", cred.model_dump(by_alias=True))
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/api/discovery")
async def discovery():
    results = {"today": [], "soaring": [], "new_songs": [], "hot_keywords": []}
    c = client()

    # 1. 热门搜索
    try:
        r_hot = await c.search.get_hot_search()
        results["hot_keywords"] = [i.k for i in r_hot][:12] if r_hot else []
    except: pass

    # 辅助函数：尝试获取榜单，失败则搜索
    async def get_list(tid, fallback_kw):
        try:
            r = await c.rank.get_rank_detail(top_id=tid)
            songs = getattr(r, "songlist", []) or getattr(r, "song", [])
            if songs: return [_song(s) for s in songs[:15]]
        except: pass
        # 降级方案：后台搜索
        try:
            r_s = await c.search.search_by_type(keyword=fallback_kw, num=15)
            return [_song(s) for s in getattr(r_s, "song", [])]
        except: return []

    # 并发抓取
    results["today"] = await get_list(26, "热歌")
    results["soaring"] = await get_list(4, "飙升榜")
    results["new_songs"] = await get_list(27, "最新流行")

    return {"success": True, "data": results}

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
import db as backend_db

@app.post("/api/register")
async def register(username: str, password: str, nickname: str, avatar: str = ""):
    uid = str(int(time.time()))
    if backend_db.create_user(uid, username, password, nickname, avatar):
        return {"success": True, "user": {"id": uid, "name": nickname, "avatar": avatar}}
    return {"success": False, "message": "用户名已存在"}

@app.post("/api/login")
async def login(username: str, password: str):
    u = backend_db.get_user_by_username(username)
    if u and u["password"] == password:
        return {"success": True, "user": {"id": u["id"], "name": u["nickname"], "avatar": u["avatar"]}}
    return {"success": False}

@app.get("/api/login/check")
async def login_check():
    return {"logged_in": (BASE / "credential.json").exists()}

# ── 设置 ────────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    return load(BASE / "settings.json", {"quality": "320mp3", "theme": "#fa586a", "lyricMode": "linear"})

@app.post("/api/settings")
async def set_settings(key: str, value: str):
    s = load(BASE / "settings.json", {})
    try: s[key] = json.loads(value)
    except: s[key] = value
    save(BASE / "settings.json", s)
    return {"success": True}

# ── 播放列表 ────────────────────────────────────
@app.get("/api/playlists")
async def pl_list(uid: str = "guest"):
    return {"success": True, "playlists": backend_db.get_playlists(uid)}

@app.post("/api/playlists")
async def pl_create(uid: str, name: str):
    backend_db.ensure_playlist_exists(uid, name)
    return {"success": True}

@app.get("/api/playlists/{name}")
async def pl_get(uid: str, name: str):
    return {"success": True, **backend_db.get_playlist_songs(uid, name)}

@app.put("/api/playlists/{name}")
async def pl_rename(uid: str, name: str, new_name: str):
    backend_db.rename_playlist(uid, name, new_name)
    return {"success": True, "name": new_name}

@app.delete("/api/playlists/{name}")
async def pl_delete(uid: str, name: str):
    backend_db.delete_playlist(uid, name)
    return {"success": True}

@app.post("/api/playlists/{name}/add")
async def pl_add(uid: str, name: str, mid: str, song_name: str, singer: str = "", album: str = "", cover: str = "", interval: int = 0):
    backend_db.add_song_to_playlist(uid, name, {"mid": mid, "name": song_name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    return {"success": True}

@app.post("/api/playlists/{name}/remove")
async def pl_remove(uid: str, name: str, mid: str):
    backend_db.remove_song_from_playlist(uid, name, mid)
    return {"success": True}

# ── 收藏 ────────────────────────────────────────
@app.get("/api/favorites/check")
async def fav_check(uid: str, mid: str):
    pl = backend_db.get_playlist_songs(uid, "我喜欢")
    return {"success": True, "is_favorite": any(s["mid"] == mid for s in pl["songs"])}

@app.post("/api/favorites/toggle")
async def fav_toggle(uid: str, mid: str, name: str, singer: str = "", album: str = "", cover: str = "", interval: int = 0):
    pl = backend_db.get_playlist_songs(uid, "我喜欢")
    is_fav = any(s["mid"] == mid for s in pl["songs"])
    if is_fav:
        backend_db.remove_song_from_playlist(uid, "我喜欢", mid)
    else:
        backend_db.add_song_to_playlist(uid, "我喜欢", {"mid": mid, "name": name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    return {"success": True, "action": "removed" if is_fav else "added"}

# ── 历史 ────────────────────────────────────────
@app.post("/api/history")
async def his_add(uid: str = "guest", mid: str = "", name: str = "", singer: str = "", album: str = "", cover: str = "", interval: int = 0):
    backend_db.add_history(uid, {"mid": mid, "name": name, "singer": singer, "album": album, "cover": cover, "interval": interval})
    return {"success": True}

@app.get("/api/history")
async def his_get(uid: str = "guest"):
    return {"success": True, "recent": backend_db.get_history(uid)}

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

@app.post("/api/covers/upload/{mid}")
async def cover_upload(mid: str, file: UploadFile = File(...)):
    try:
        p = BASE / "covers" / f"{mid}.jpg"
        p.write_bytes(await file.read())
        return {"success": True, "url": f"/api/covers/view/{mid}"}
    except Exception as e: return {"success": False, "message": str(e)}

@app.get("/api/covers/view/{mid}")
async def cover_view(mid: str):
    p = BASE / "covers" / f"{mid}.jpg"
    if p.exists():
        return FileResponse(p)
    return StreamingResponse(iter([]), status_code=404)

# ── 下载 ────────────────────────────────────────
@app.get("/api/download")
async def download(mid: str, quality: str = "320mp3", name: str = "", singer: str = "", album: str = "", cover: str = ""):
    try:
        u = await client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=Q.get(quality, SongFileType.MP3_320))
        if not (u and u.data and u.data[0].purl): return {"success": False, "message": "无法获取下载链接"}
        url = f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}"
        ext = {"128mp3":"mp3","320mp3":"mp3","ogg":"ogg","flac":"flac"}.get(quality, "mp3")
        safe = f"{singer} - {name}" if singer and name else mid
        safe = "".join(c for c in safe if c not in r'\/:*?"<>|')
        filename = f"{safe}.{ext}"
        import requests as _r
        resp = _r.get(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://y.qq.com/"}, stream=True, timeout=60)
        return StreamingResponse(resp.iter_content(chunk_size=65536),
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
            media_type="audio/mpeg")
    except Exception as e: return {"success": False, "message": str(e)}

@app.get("/api/batch-download")
async def batch_download(mids: str, names: str, singers: str, albums: str = "", covers: str = "", quality: str = "320mp3"):
    m_list = mids.split(",")
    n_list = names.split("||")
    s_list = singers.split("||")
    success_count = 0
    for i in range(len(m_list)):
        try:
            res = await download(m_list[i], quality, n_list[i], s_list[i])
            if res.get("success"): success_count += 1
        except: pass
    return {"success": True, "message": f"批量下载完成，成功 {success_count}/{len(m_list)}"}

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
    # 全面支持的音频格式：mp3, flac, ogg, m4a, wav, aac, opus, ape, wma, mka, dsf, dff
    valid_exts = (".mp3", ".flac", ".ogg", ".m4a", ".wav", ".aac", ".opus", ".ape", ".wma", ".mka", ".dsf", ".dff")
    for f in sorted(DOWNLOADS.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in valid_exts:
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

@app.get("/api/stream-local")
async def stream_local(filename: str):
    fp = (DOWNLOADS / filename).resolve()
    if not str(fp).startswith(str(DOWNLOADS.resolve())): return StreamingResponse(iter([]), status_code=403)
    if not fp.exists(): return StreamingResponse(iter([]), status_code=404)
    return FileResponse(fp)

# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8899)))
