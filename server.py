"""
West Trail Music — QQ音乐 Apple Music 风格客户端
FastAPI 后端：搜索 / 播放 / 下载 / 歌词 / 播放列表 / 封面缓存 / 扫码登录
"""
import asyncio
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from fastapi import FastAPI, Query, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from qqmusic_api import Client, Credential
from qqmusic_api.modules.song import SongFileInfo, SongFileType

from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, ID3NoHeaderError
from mutagen.flac import FLAC, Picture
from mutagen.mp4 import MP4, MP4Cover

# ── 路径 ──────────────────────────────────────────
if getattr(sys, "frozen", False):
    _RESOURCE_DIR = Path(sys._MEIPASS)
    _USER_DIR = Path(sys.executable).parent
else:
    _RESOURCE_DIR = Path(__file__).parent
    _USER_DIR = _RESOURCE_DIR

DOWNLOADS_DIR   = _USER_DIR / "downloads";   DOWNLOADS_DIR.mkdir(exist_ok=True)
PLAYLISTS_DIR    = _USER_DIR / "playlists";    PLAYLISTS_DIR.mkdir(exist_ok=True)
COVERS_DIR       = _USER_DIR / "covers";       COVERS_DIR.mkdir(exist_ok=True)
CREDENTIAL_FILE  = _USER_DIR / "credential.json"
SETTINGS_FILE    = _USER_DIR / "settings.json"
HISTORY_FILE     = _USER_DIR / "history.json"

# ── 音质映射 ──────────────────────────────────────
QUALITY_MAP: dict[str, tuple[str, SongFileType]] = {
    "128mp3": ("MP3 128k", SongFileType.MP3_128),
    "320mp3": ("MP3 320k", SongFileType.MP3_320),
    "flac":   ("FLAC 无损", SongFileType.FLAC),
    "ogg192": ("OGG 192k", SongFileType.OGG_192),
    "ogg320": ("OGG 320k", SongFileType.OGG_320),
    "acc192": ("ACC 192k", SongFileType.ACC_192),
}
EXT_MAP = {"128mp3":"mp3","320mp3":"mp3","flac":"flac","ogg192":"ogg","ogg320":"ogg","acc192":"m4a"}

# ── 凭证 ──────────────────────────────────────────
def load_credential():
    if CREDENTIAL_FILE.exists():
        with open(CREDENTIAL_FILE, "r", encoding="utf-8") as f:
            return Credential(**json.load(f))
    # Fallback: read from environment variable (for Railway/Render deployment)
    env_cred = os.environ.get("CREDENTIAL_JSON", "")
    if env_cred:
        return Credential(**json.loads(env_cred))
    return None

def save_credential(cred: Credential):
    CREDENTIAL_FILE.write_text(json.dumps(cred.model_dump(by_alias=True), ensure_ascii=False, indent=2), encoding="utf-8")

def get_client():
    cred = load_credential()
    return Client(credential=cred) if cred else Client()

async def refresh_and_save():
    cred = load_credential()
    if not cred: return False
    try:
        new_cred = await Client(credential=cred).login.refresh_credential(cred)
        save_credential(new_cred)
        return True
    except Exception:
        return False

# ── 元数据 ────────────────────────────────────────
def embed_metadata(filepath: str, title: str, artist: str, album: str, cover_data: bytes | None):
    try:
        ext = Path(filepath).suffix.lower()
        if ext == ".mp3":
            try: audio = ID3(filepath)
            except ID3NoHeaderError: audio = ID3()
            audio.add(TIT2(encoding=3, text=title))
            audio.add(TPE1(encoding=3, text=artist))
            if album: audio.add(TALB(encoding=3, text=album))
            if cover_data: audio.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_data))
            audio.save(filepath, v2_version=3)
        elif ext == ".flac":
            audio = FLAC(filepath)
            audio["title"]=title; audio["artist"]=artist
            if album: audio["album"]=album
            if cover_data:
                pic=Picture(); pic.type=3; pic.mime="image/jpeg"; pic.desc="Cover"; pic.data=cover_data
                audio.add_picture(pic)
            audio.save()
        elif ext == ".m4a":
            audio=MP4(filepath)
            audio["\xa9nam"]=title; audio["\xa9ART"]=artist
            if album: audio["\xa9alb"]=album
            if cover_data: audio["covr"]=[MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
            audio.save()
    except Exception as e:
        print(f"元数据写入失败: {e}")

_download_status: dict[str, dict] = {}

# ── 设置 / 历史 持久化 ────────────────────────────
def load_json(path: Path, default: dict) -> dict:
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except Exception: pass
    return default

def save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_settings() -> dict:
    return load_json(SETTINGS_FILE, {"theme":"#fa586a","quality":"320mp3","volume":1.0,"lyricMode":"linear"})

def load_history() -> list[dict]:
    return load_json(HISTORY_FILE, {"recent":[]}).get("recent",[])

def save_history(songs: list[dict]):
    save_json(HISTORY_FILE, {"recent": songs[-50:]})  # 最多保留 50 条

# ── 封面缓存 ──────────────────────────────────────
def get_cover_path(mid: str) -> Path:
    return COVERS_DIR / f"{mid}.jpg"

def cache_cover_from_url(mid: str, url: str) -> bool:
    if not url: return False
    p = get_cover_path(mid)
    if p.exists(): return True
    try:
        req = urllib.request.Request(url, headers={"Referer":"https://y.qq.com/","User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            p.write_bytes(r.read())
        return True
    except Exception:
        return False

# ── 播放列表 ──────────────────────────────────────
def _list_playlists() -> list[str]:
    return sorted([f.stem for f in PLAYLISTS_DIR.glob("*.json")])

def _playlist_path(name: str) -> Path:
    safe = re.sub(r'[\\/:*?"<>|]', "_", name)
    return PLAYLISTS_DIR / f"{safe}.json"

def _read_playlist(name: str) -> dict:
    p = _playlist_path(name)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"name": name, "songs": []}

def _write_playlist(name: str, data: dict):
    _playlist_path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ═══════════════════════════════════════════════════
app = FastAPI(title="West Trail Music")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((_RESOURCE_DIR / "index.html").read_text(encoding="utf-8"))

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── 搜索 ──────────────────────────────────────────
@app.get("/api/search")
async def search(keyword: str = Query(..., min_length=1), num: int = Query(default=30, le=50)):
    client = get_client()
    try:
        result = await client.search.search_by_type(keyword=keyword, num=num)
    except Exception as e:
        return {"success": False, "message": f"搜索失败: {e}"}
    if not hasattr(result, "song") or not result.song:
        return {"success": True, "songs": [], "total": 0}
    songs = []
    for song in result.song:
        singers = [s.name for s in song.singer] if song.singer else ["未知"]
        album_name = song.album.name if hasattr(song,"album") and song.album else ""
        interval = getattr(song,"interval",0)
        m,s_=divmod(interval,60)
        cover = song.album.cover_url() if hasattr(song,"album") and hasattr(song.album,"cover_url") else ""
        songs.append({
            "mid":song.mid,"name":song.name,"singer":" / ".join(singers),
            "album":album_name,"duration":f"{m}:{s_:02d}","interval":interval,"cover":cover
        })
    return {"success":True,"songs":songs,"total":getattr(result,"total",len(songs))}


# ── 播放 ──────────────────────────────────────────
@app.get("/api/play-url")
async def get_play_url(mid: str = Query(...), quality: str = Query(default="128mp3")):
    if quality not in QUALITY_MAP: return {"success":False,"message":f"不支持的音质: {quality}"}
    _, ft = QUALITY_MAP[quality]
    cred = load_credential()
    async def try_url():
        u = await get_client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=ft, credential=cred)
        return f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}" if u.data and u.data[0].purl else None
    url = await try_url()
    if url: return {"success":True,"url":url}
    if await refresh_and_save():
        url = await try_url()
        if url: return {"success":True,"url":url}
    return {"success":False,"message":"无法获取播放链接"}

@app.get("/api/stream-play")
async def stream_play(mid: str = Query(...), quality: str = Query(default="128mp3")):
    if quality not in QUALITY_MAP: return StreamingResponse(iter([]),status_code=404)
    _, ft = QUALITY_MAP[quality]
    cred = load_credential()
    urls = await get_client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=ft, credential=cred)
    if not urls.data or not urls.data[0].purl: return StreamingResponse(iter([]),status_code=404)
    cdn = f"http://ws.stream.qqmusic.qq.com/{urls.data[0].purl}"
    import requests as _r
    resp = _r.get(cdn, headers={"User-Agent":"Mozilla/5.0","Referer":"https://y.qq.com/"}, stream=True, timeout=30)
    return StreamingResponse(resp.iter_content(chunk_size=65536), status_code=200, media_type="audio/mpeg")


# ── 歌词 ──────────────────────────────────────────
@app.get("/api/lyrics")
async def get_lyrics(mid: str = Query(...)):
    try:
        r = await get_client().lyric.get_lyric(mid)
        d = r.decrypt()
        return {"success":True,"lyric":d.lyric}
    except Exception as e:
        return {"success":False,"message":str(e)}


# ── 封面缓存 ──────────────────────────────────────
@app.get("/api/covers/{mid}")
async def serve_cover(mid: str):
    p = get_cover_path(mid)
    if p.exists(): return FileResponse(p, media_type="image/jpeg")
    return FileResponse(_RESOURCE_DIR / "default-cover.svg" if (_RESOURCE_DIR / "default-cover.svg").exists() else None, status_code=404)

@app.post("/api/covers/upload/{mid}")
async def upload_cover(mid: str, file: UploadFile = File(...)):
    try:
        data = await file.read()
        if len(data) > 10 * 1024 * 1024: return {"success":False,"message":"文件不能超过 10MB"}
        get_cover_path(mid).write_bytes(data)
        return {"success":True,"message":"封面已更新","url":f"/api/covers/{mid}"}
    except Exception as e:
        return {"success":False,"message":str(e)}

@app.get("/api/covers/cache/{mid}")
async def cache_cover(mid: str, url: str = Query(...)):
    """缓存远程封面到本地"""
    ok = cache_cover_from_url(mid, url)
    return {"success":ok}


# ── 下载 ──────────────────────────────────────────
@app.get("/api/download")
async def download(
    mid: str = Query(...), quality: str = Query(default="320mp3"),
    name: str = Query(default=""), singer: str = Query(default=""),
    album: str = Query(default=""), cover: str = Query(default=""),
):
    if quality not in QUALITY_MAP: return {"success":False,"message":f"不支持的音质: {quality}"}
    _, ft = QUALITY_MAP[quality]
    ext = EXT_MAP.get(quality,"mp3")
    safe = f"{singer} - {name}" if singer and name else mid
    safe = "".join(c for c in safe if c not in r'\/:*?"<>|')
    filename = f"{safe}.{ext}"
    fp = DOWNLOADS_DIR / filename
    _download_status[mid]={"progress":0,"status":"fetching_url","filename":filename}
    cred = load_credential()
    async def fetch():
        u = await get_client().song.get_song_urls([SongFileInfo(mid=mid)], file_type=ft, credential=cred)
        return f"http://ws.stream.qqmusic.qq.com/{u.data[0].purl}" if u.data and u.data[0].purl else None
    dl_url = await fetch()
    if not dl_url:
        if await refresh_and_save(): dl_url = await fetch()
    if not dl_url:
        _download_status[mid]={"progress":0,"status":"error","filename":filename,"message":"无法获取下载链接"}
        return {"success":False,"message":"无法获取下载链接"}
    _download_status[mid]={"progress":10,"status":"downloading","filename":filename}
    cover_data = None
    if cover:
        try:
            req=urllib.request.Request(cover,headers={"Referer":"https://y.qq.com/","User-Agent":"Mozilla/5.0"})
            with urllib.request.urlopen(req,timeout=10) as r: cover_data=r.read()
        except Exception: pass
    def do():
        try:
            urllib.request.urlretrieve(dl_url, fp)
            embed_metadata(str(fp), name, singer, album, cover_data)
            _download_status[mid]={"progress":100,"status":"done","filename":filename,"path":str(fp)}
        except Exception as e:
            _download_status[mid]={"progress":0,"status":"error","filename":filename,"message":str(e)}
    await asyncio.to_thread(do)
    if _download_status[mid]["status"]=="done":
        sz=os.path.getsize(fp)/(1024*1024)
        return {"success":True,"message":f"下载完成: {filename}","filename":filename,"size_mb":round(sz,2)}
    return {"success":False,"message":_download_status[mid].get("message","下载失败")}

@app.get("/api/batch-download")
async def batch_download(
    mids: str = Query(...), names: str = Query(default=""), singers: str = Query(default=""),
    albums: str = Query(default=""), covers: str = Query(default=""), quality: str = Query(default="320mp3"),
):
    ml=mids.split(","); n=len(ml)
    def sp(s): return s.split("||") if s else [""]*n
    nl,sl,al,cl=sp(names),sp(singers),sp(albums),sp(covers)
    results=[]
    for i,mid in enumerate(ml):
        try:
            r=await download(mid=mid,quality=quality,name=nl[i] if i<n else"",singer=sl[i] if i<n else"",album=al[i] if i<n else"",cover=cl[i] if i<n else"")
            results.append(r)
        except Exception as e: results.append({"success":False,"message":str(e),"mid":mid})
        await asyncio.sleep(0.5)
    ok=sum(1 for r in results if r.get("success"))
    return {"success":True,"message":f"完成: {ok}/{n} 首","results":results}

@app.get("/api/download-status")
async def download_status(mid: str = Query(...)):
    return _download_status.get(mid,{"status":"unknown"})

@app.get("/api/downloads")
async def list_downloads():
    files=[]
    for f in sorted(DOWNLOADS_DIR.iterdir(),key=lambda x:x.stat().st_mtime,reverse=True):
        if f.suffix.lower() in(".mp3",".flac",".ogg",".m4a"):
            sz=f.stat().st_size/(1024*1024)
            mt=time.strftime("%Y-%m-%d %H:%M",time.localtime(f.stat().st_mtime))
            files.append({"filename":f.name,"size_mb":round(sz,2),"time":mt})
    return {"success":True,"files":files}

@app.get("/api/delete-download")
async def delete_download(filename: str = Query(...)):
    fp=(DOWNLOADS_DIR/filename).resolve()
    if not str(fp).startswith(str(DOWNLOADS_DIR.resolve())): return {"success":False,"message":"非法路径"}
    if fp.exists(): fp.unlink(); return {"success":True,"message":f"已删除: {filename}"}
    return {"success":False,"message":"文件不存在"}

@app.get("/api/open-folder")
async def open_folder():
    if sys.platform == 'win32':
        os.startfile(str(DOWNLOADS_DIR))
    else:
        pass  # Linux 不支持
    return {"success":True}


# ── 播放列表 ──────────────────────────────────────
@app.get("/api/playlists")
async def list_playlists():
    return {"success":True,"playlists":_list_playlists()}

@app.post("/api/playlists")
async def create_playlist(name: str = Query(..., min_length=1)):
    safe=re.sub(r'[\\/:*?"<>|]',"_",name)
    p=_playlist_path(safe)
    if p.exists(): return {"success":False,"message":"播放列表已存在"}
    _write_playlist(safe,{"name":name,"songs":[]})
    return {"success":True,"name":safe}

@app.put("/api/playlists/{name}")
async def rename_playlist(name: str, new_name: str = Query(..., min_length=1)):
    op=_playlist_path(name)
    if not op.exists(): return {"success":False,"message":"播放列表不存在"}
    safe_new=re.sub(r'[\\/:*?"<>|]',"_",new_name)
    np=_playlist_path(safe_new)
    if np.exists(): return {"success":False,"message":"目标名称已存在"}
    data=_read_playlist(name); data["name"]=new_name
    _write_playlist(safe_new,data); op.unlink()
    return {"success":True,"name":safe_new}

@app.delete("/api/playlists/{name}")
async def delete_playlist(name: str):
    p=_playlist_path(name)
    if not p.exists(): return {"success":False,"message":"播放列表不存在"}
    p.unlink(); return {"success":True}

@app.get("/api/playlists/{name}")
async def get_playlist(name: str):
    if not _playlist_path(name).exists(): return {"success":False,"message":"播放列表不存在"}
    return {"success":True,**_read_playlist(name)}

@app.post("/api/playlists/{name}/add")
async def add_to_playlist(
    name: str, mid: str = Query(...), song_name: str = Query(...),
    singer: str = Query(default=""), album: str = Query(default=""),
    cover: str = Query(default=""), interval: int = Query(default=0),
):
    if not _playlist_path(name).exists(): return {"success":False,"message":"播放列表不存在"}
    data=_read_playlist(name)
    if any(s["mid"]==mid for s in data["songs"]): return {"success":False,"message":"歌曲已在列表中"}
    data["songs"].append({"mid":mid,"name":song_name,"singer":singer,"album":album,"cover":cover,"interval":interval})
    _write_playlist(name,data)
    return {"success":True,"count":len(data["songs"])}

@app.delete("/api/playlists/{name}/remove")
async def remove_from_playlist(name: str, mid: str = Query(...)):
    if not _playlist_path(name).exists(): return {"success":False,"message":"播放列表不存在"}
    data=_read_playlist(name)
    data["songs"]=[s for s in data["songs"] if s["mid"]!=mid]
    _write_playlist(name,data)
    return {"success":True,"count":len(data["songs"])}

@app.put("/api/playlists/{name}/reorder")
async def reorder_playlist(name: str, order: str = Query(...)):
    """order: mid1,mid2,mid3,..."""
    if not _playlist_path(name).exists(): return {"success":False,"message":"播放列表不存在"}
    data=_read_playlist(name)
    order_list=order.split(",")
    song_map={s["mid"]:s for s in data["songs"]}
    new_songs=[song_map[mid] for mid in order_list if mid in song_map]
    # 保留不在 order 中的歌曲
    for s in data["songs"]:
        if s["mid"] not in order_list: new_songs.append(s)
    data["songs"]=new_songs
    _write_playlist(name,data)
    return {"success":True}


# ── 设置 ──────────────────────────────────────────
@app.get("/api/settings")
async def get_settings():
    return {"success":True,**load_settings()}

@app.post("/api/settings")
async def save_settings(key: str = Query(...), value: str = Query(...)):
    s=load_settings()
    try: s[key]=json.loads(value)
    except Exception: s[key]=value
    save_json(SETTINGS_FILE,s)
    return {"success":True}


# ── 搜索历史 ──────────────────────────────────────
@app.get("/api/history")
async def get_history():
    return {"success":True,"recent":load_history()}

@app.post("/api/history")
async def add_history(
    mid: str = Query(...), name: str = Query(...), singer: str = Query(default=""),
    cover: str = Query(default=""), interval: int = Query(default=0),
):
    recent=load_history()
    recent=[r for r in recent if r["mid"]!=mid]
    recent.insert(0,{"mid":mid,"name":name,"singer":singer,"cover":cover,"interval":interval})
    save_history(recent)
    # 异步缓存封面
    if cover: asyncio.create_task(asyncio.to_thread(cache_cover_from_url,mid,cover))
    return {"success":True}


# ── 扫码登录 ──────────────────────────────────────
import base64 as _b64
from qqmusic_api.models.login import QRLoginType as _QLT, QRCodeLoginEvents as _QLE
from qqmusic_api import Credential as _Cred

_qr_obj: dict = {}  # 存储当前 QR 对象: {"qr": QR, "client": Client, "status": str, "msg": str, "img": str}

@app.get("/api/login/qrcode")
async def get_login_qrcode():
    """获取扫码登录二维码（返回 base64 PNG）"""
    global _qr_obj
    try:
        client = Client()
        qr = await client.login.get_qrcode(_QLT.QQ)
        img_b64 = "data:image/png;base64," + _b64.b64encode(qr.data).decode()
        _qr_obj = {"qr": qr, "client": client, "status": "waiting", "msg": "请用 QQ 扫描二维码", "img": img_b64}

        async def poll():
            while True:
                await asyncio.sleep(2)
                try:
                    result = await client.login.check_qrcode(qr)
                except Exception:
                    _qr_obj["status"] = "error"
                    _qr_obj["msg"] = "检查登录状态失败"
                    return
                event = result.event
                if event == _QLE.DONE:
                    cred = client.credential or result.credential
                    if cred:
                        save_credential(cred)
                        _qr_obj["status"] = "done"
                        _qr_obj["msg"] = "登录成功"
                    else:
                        _qr_obj["status"] = "error"
                        _qr_obj["msg"] = "登录失败：未获取到凭证"
                    return
                elif event == _QLE.SCAN:
                    _qr_obj["status"] = "scanned"
                    _qr_obj["msg"] = "已扫描，请在手机上确认"
                elif event == _QLE.CONF:
                    _qr_obj["status"] = "confirmed"
                    _qr_obj["msg"] = "已确认，正在登录..."
                elif event == _QLE.TIMEOUT:
                    _qr_obj["status"] = "expired"
                    _qr_obj["msg"] = "二维码已过期，请重新获取"
                    return
                elif event == _QLE.REFUSE:
                    _qr_obj["status"] = "refused"
                    _qr_obj["msg"] = "已取消登录"
                    return

        asyncio.create_task(poll())
        return {"success": True, "img": img_b64, "status": "waiting"}
    except Exception as e:
        return {"success": False, "message": f"获取二维码失败: {e}"}

@app.get("/api/login/status")
async def login_status():
    if not _qr_obj:
        return {"success": True, "status": "idle", "message": ""}
    return {"success": True, "status": _qr_obj.get("status", "idle"), "message": _qr_obj.get("msg", "")}

@app.get("/api/login/check")
async def check_login():
    """检查是否已登录"""
    cred = load_credential()
    return {"success": True, "logged_in": cred is not None}


# ═══════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    print(f"下载: {DOWNLOADS_DIR} | 凭证: {CREDENTIAL_FILE} | 封面缓存: {COVERS_DIR} | 播放列表: {PLAYLISTS_DIR}")
    port = int(os.environ.get("PORT", 8899))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
