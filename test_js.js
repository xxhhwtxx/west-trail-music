
// ═══════════════════════════════════════════════
//  全局状态
// ═══════════════════════════════════════════════
const A=document.getElementById('audio'),
  Q=()=>document.getElementById('quality').value,
  $=id=>document.getElementById(id);
// Unlock audio for mobile (must be triggered by user gesture)
document.addEventListener('click',()=>{A.play().then(()=>A.pause()).catch(()=>{})},{once:true});
document.addEventListener('touchend',()=>{A.play().then(()=>A.pause()).catch(()=>{})},{once:true});
let playlist=[],idx=-1,currentSong=null,searchData=[],shuffle=false,ctxTarget=null;
let lyricMode='linear',lyricData=[],rafId,analyser,spectrumCtx;

// ═══════════════════════════════════════════════
//  PC 快捷键支持 (空格, 左右, 上下)
// ═══════════════════════════════════════════════
document.addEventListener('keydown', e => {
  if (['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)) return; // 避免输入框冲突
  if (e.code === 'Space') {
    e.preventDefault(); togglePlay();
  } else if (e.code === 'ArrowLeft') {
    e.preventDefault(); playPrev();
  } else if (e.code === 'ArrowRight') {
    e.preventDefault(); playNext();
  } else if (e.code === 'ArrowUp') {
    e.preventDefault(); A.volume = Math.min(1, A.volume + 0.1); updateVolFill();
  } else if (e.code === 'ArrowDown') {
    e.preventDefault(); A.volume = Math.max(0, A.volume - 0.1); updateVolFill();
  }
});

// ═══════════════════════════════════════════════
//  Toast
// ═══════════════════════════════════════════════
function toast(m,c=''){const d=document.createElement('div');d.className='toast '+c;d.textContent=m;$('toasts').appendChild(d);setTimeout(()=>d.remove(),2500)}

// ═══════════════════════════════════════════════
//  导航 & 视图
// ═══════════════════════════════════════════════
document.querySelectorAll('.nav-item').forEach(el=>{
  el.addEventListener('click',()=>{
    document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
    el.classList.add('active');
    switchView(el.dataset.view);
  });
});

function switchView(view){
  $('btnBatch').style.display='none';
  if(view==='search') $('content').innerHTML = `<div class="empty"><div class="empty-icon">🔍</div><div class="empty-title">搜索你喜欢的音乐</div><div class="empty-sub">输入关键词开始搜索</div></div>`;
  else if(view==='downloads') loadDownloads();
  else if(view==='recent') loadRecent();
  else if(view==='favorites') {
    // Make sure the playlist exists in db, otherwise the api creates it implicitly or we handle it
    openPlaylist('我喜欢');
  }
}
switchView('search');

function toggleSidebar(){
  document.querySelector('.sidebar').classList.toggle('open');
  $('sidebarOverlay').classList.toggle('show');
}
// Close sidebar when nav item clicked on mobile
document.querySelectorAll('.nav-item').forEach(el=>{
  el.addEventListener('click',()=>{
    document.querySelector('.sidebar').classList.remove('open');
    $('sidebarOverlay').classList.remove('show');
  });
});

// ═══════════════════════════════════════════════
//  搜索
// ═══════════════════════════════════════════════
async function search(){
  const kw=$('keyword').value.trim();if(!kw)return;
  $('content').innerHTML='<div class="empty"><div class="empty-icon">⏳</div><div class="empty-title">搜索中…</div></div>';
  try{
    const r=await fetch(`/api/search?keyword=${encodeURIComponent(kw)}&num=30`),d=await r.json();
    if(!d.success){toast(d.message,'warn');return}
    searchData=d.songs;
    const h=$('btnBatch');h.style.display='inline-block';h.disabled=true;h.textContent='批量下载';
    if(!d.songs.length){$('content').innerHTML='<div class="empty"><div class="empty-icon">🔍</div><div class="empty-title">没有找到相关歌曲</div></div>';return}
    let html=`<div class="section-title">「${kw}」的搜索结果</div><div class="song-list-header"><span></span><span>歌曲</span><span>专辑</span><span style="text-align:center">⏱</span><span></span></div>`;
    d.songs.forEach((s,i)=>{
      html+=`<div class="song-row" ondblclick="playSearchResult(${i})">
        <span class="idx">${i+1}</span>
        <div class="info" onclick="playSearchResult(${i})">
          <img src="${s.cover||''}" onerror="this.style.display='none'" loading="lazy">
          <div class="meta"><div class="t">${esc(s.name)}</div><div class="a">${esc(s.singer)}</div></div>
        </div>
        <span class="album">${esc(s.album)}</span>
        <span class="dur">${s.duration}</span>
        <span class="actions">
          <button onclick="event.stopPropagation();toggleFavorite('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.album)}','${escJs(s.cover)}',${s.interval})" title="收藏">♥</button>
          <button onclick="event.stopPropagation();addToPlaylistPrompt('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.album)}','${escJs(s.cover)}',${s.interval})" title="添加到播放列表">＋</button>
          <button onclick="event.stopPropagation();downloadSong('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.album)}','${escJs(s.cover)}')" title="下载">⬇</button>
        </span>
      </div>`;
    });
    $('content').innerHTML=html;
    // Render checkboxes for batch
    const hdr=$('content').querySelector('.song-list-header');
    if(hdr) hdr.children[0].innerHTML='<input type="checkbox" id="selAll" onchange="toggleAll()">';
    d.songs.forEach((s,i)=>{
      const row=$('content').querySelectorAll('.song-row')[i];
      const cb=document.createElement('input');
      cb.type='checkbox';cb.dataset.mid=s.mid;cb.onchange=updateBatch;
      const idxCell=row.querySelector('.idx');
      idxCell.innerHTML='';idxCell.appendChild(cb);
    });
  }catch(e){toast('搜索失败','warn')}
}

function toggleAll(){
  const c=document.getElementById('selAll')?.checked;
  document.querySelectorAll('#content input[type=checkbox]').forEach(cb=>cb.checked=c);
  updateBatch();
}
function updateBatch(){
  const sel=[...document.querySelectorAll('#content input[type=checkbox]')].filter(cb=>cb.checked);
  const b=$('btnBatch');b.disabled=sel.length===0;b.textContent=sel.length?`下载 (${sel.length})`:'批量下载';
}
function playSearchResult(i){
  const s=searchData[i];if(!s)return;
  playSong(s.mid,s.name,s.singer,s.cover,s.interval);
  addHistory(s.mid,s.name,s.singer,s.album||'',s.cover,s.interval);
  // Mark as playing
  document.querySelectorAll('.song-row').forEach(r=>r.classList.remove('playing'));
  const row=document.querySelectorAll('.song-row')[i];
  if(row)row.classList.add('playing');
}
async function batchDownload(){
  const sel=[...document.querySelectorAll('#content input[type=checkbox]')].filter(cb=>cb.checked);
  if(!sel.length)return;
  const data=sel.map(cb=>{const s=searchData.find(x=>x.mid===cb.dataset.mid);return s||{};});
  const mids=data.map(s=>s.mid).join(',');
  const names=data.map(s=>s.name).join('||');
  const singers=data.map(s=>s.singer).join('||');
  const albums=data.map(s=>s.album||'').join('||');
  const covers=data.map(s=>s.cover||'').join('||');
  toast(`正在下载 ${data.length} 首歌…`,'info');
  try{
    const r=await fetch(`/api/batch-download?mids=${mids}&names=${encodeURIComponent(names)}&singers=${encodeURIComponent(singers)}&albums=${encodeURIComponent(albums)}&covers=${encodeURIComponent(covers)}&quality=${Q()}`);
    const d=await r.json();
    toast(d.message,d.success?'':'warn');
  }catch(e){toast('下载失败','warn')}
}

function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
function escJs(s){return s.replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'\\"')}

// ═══════════════════════════════════════════════
//  播放器
// ═══════════════════════════════════════════════
function playSong(mid,name,singer,cover,interval){
  currentSong={mid,name,singer,cover,interval};
  $('npName').textContent=name;$('npArtist').textContent=singer;
  $('durTime').textContent=fmtTime(interval);
  if(cover){
    $('npCover').src=cover;$('npCover').style.display='';$('npCoverFallback').style.display='none';
    $('vinylImg').src=cover;
    // 沉浸式动态背景更新
    const mb=$('mainBg'); mb.src=cover; mb.style.opacity=0.35;
  }else{
    $('npCover').style.display='none';$('npCoverFallback').style.display='';
    $('mainBg').style.opacity=0;
  }
  A.src=`/api/stream-play?mid=${mid}&quality=${Q()}`;
  var p=A.play();if(p!==undefined){p.catch(()=>{toast('点击播放按钮开始播放','info')})};
  $('playBtn').textContent='⏸';
  // Cache cover
  if(cover) fetch(`/api/covers/cache/${mid}?url=${encodeURIComponent(cover)}`);
  loadLyrics(mid);
  // Add to playlist for prev/next
  if(!playlist.find(s=>s.mid===mid)) playlist.push({mid,name,singer,cover,interval});
  checkCurrentFavorite(mid);
  idx=playlist.findIndex(s=>s.mid===mid);
  initSpectrum();
}
function togglePlay(){if(A.paused){A.play();$('playBtn').textContent='⏸'}else{A.pause();$('playBtn').textContent='▶'}}
function prevSong(){if(playlist.length){idx=shuffle?Math.floor(Math.random()*playlist.length):(idx-1+playlist.length)%playlist.length;const s=playlist[idx];playSong(s.mid,s.name,s.singer,s.cover,s.interval)}}
function nextSong(){if(playlist.length){idx=shuffle?Math.floor(Math.random()*playlist.length):(idx+1)%playlist.length;const s=playlist[idx];playSong(s.mid,s.name,s.singer,s.cover,s.interval)}}
function toggleShuffle(){shuffle=!shuffle;$('shuffleBtn').style.color=shuffle?'var(--accent)':'';toast(shuffle?'随机播放':'顺序播放')}

A.addEventListener('ended',nextSong);
A.addEventListener('timeupdate',()=>{
  const pct=A.duration?(A.currentTime/A.duration)*100:0;
  $('progFill').style.width=pct+'%';$('curTime').textContent=fmtTime(A.currentTime);
  updateLyricHighlight();
});
A.addEventListener('loadedmetadata',()=>{$('durTime').textContent=fmtTime(A.duration)});
function seek(e){const b=e.currentTarget;A.currentTime=(e.offsetX/b.offsetWidth)*A.duration}
function fmtTime(s){const m=Math.floor(s/60),sec=Math.floor(s%60);return m+':'+(sec<10?'0':'')+sec}
function setVol(e){const pct=e.offsetX/e.currentTarget.offsetWidth;A.volume=Math.max(0,Math.min(1,pct));$('volFill').style.width=(A.volume*100)+'%';updateMuteIcon()}
function toggleMute(){A.muted=!A.muted;updateMuteIcon()}
function updateMuteIcon(){$('muteBtn').textContent=A.muted||A.volume===0?'🔇':'🔊'}
A.volume=0.8;$('volFill').style.width='80%';

// ═══════════════════════════════════════════════
//  频谱
// ═══════════════════════════════════════════════
function initSpectrum(){
  if(!analyser){
    try{
      const ctx=new(window.AudioContext||window.webkitAudioContext)();
      analyser=ctx.createAnalyser();analyser.fftSize=256;
      const src=ctx.createMediaElementSource(A);
      src.connect(analyser);analyser.connect(ctx.destination);
    }catch(e){return}
  }
  spectrumCtx=$('spectrum').getContext('2d');
  drawSpectrum();
}
function drawSpectrum(){
  if(!analyser||A.paused){if(rafId)cancelAnimationFrame(rafId);rafId=requestAnimationFrame(()=>{spectrumCtx.clearRect(0,0,400,60);drawSpectrum()});return}
  const c=spectrumCtx,w=400,h=60,data=new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  c.clearRect(0,0,w,h);
  const barW=3,gap=1,bars=Math.min(64,data.length);
  for(let i=0;i<bars;i++){
    const v=data[i]/255,barH=v*h*0.8+2;
    const x=i*(barW+gap);
    const grad=c.createLinearGradient(x,0,x,h);
    grad.addColorStop(0,`hsl(${340+v*20},80%,${50+v*30}%)`);
    grad.addColorStop(1,'rgba(250,88,106,.3)');
    c.fillStyle=grad;
    c.fillRect(x,h-barH,barW,barH);
  }
  rafId=requestAnimationFrame(drawSpectrum);
}

// ═══════════════════════════════════════════════
//  歌词
// ═══════════════════════════════════════════════
async function loadLyrics(mid){
  try{
    const r=await fetch(`/api/lyrics?mid=${mid}`),d=await r.json();
    if(d.success&&d.lyric){lyricData=parseLyric(d.lyric);renderLyrics();return}
  }catch(e){}
  lyricData=[];$('lyricLines').innerHTML='<div class="empty"><div class="empty-icon">🎤</div><div class="empty-title">暂无歌词</div></div>';
}
function parseLyric(text){
  const lines=[];
  text.split('\n').forEach(line=>{
    const m=line.match(/^\[(\d+):(\d+(?:\.\d+)?)\](.*)/);
    if(m)lines.push({time:parseInt(m[1])*60+parseFloat(m[2]),text:m[3].trim()||'…'});
  });
  return lines.sort((a,b)=>a.time-b.time);
}
function renderLyrics(){
  if(!lyricData.length){$('lyricLines').innerHTML='<div class="empty"><div class="empty-icon">🎤</div><div class="empty-title">暂无歌词</div></div>';return}
  // Estimate per-word timing: each word in line i gets equal share of time until next line (or +4s)
  $('lyricLines').innerHTML=lyricData.map((l,i)=>{
    const nextTime=i+1<lyricData.length?lyricData[i+1].time:l.time+4;
    const dur=Math.max(0.1,nextTime-l.time);
    const chars=l.text.split('');
    const wordMs=dur/chars.length;
    if(lyricMode==='karaoke'){
      const words=chars.map((c,j)=>`<span class="word" data-ts="${(l.time+j*wordMs).toFixed(2)}">${c}</span>`).join('');
      return `<div class="lyric-line karaoke" data-idx="${i}" data-time="${l.time}">${words}</div>`;
    }
    const words=chars.map((c,j)=>`<span class="word" data-ts="${(l.time+j*wordMs).toFixed(2)}">${c}</span>`).join('');
    return `<div class="lyric-line" data-idx="${i}" data-time="${l.time}">${words}</div>`;
  }).join('');
}
function updateLyricHighlight(){
  if(!lyricData.length)return;
  const t=A.currentTime;let active=-1;
  for(let i=lyricData.length-1;i>=0;i--){if(lyricData[i].time<=t){active=i;break}}
  document.querySelectorAll('#lyricLines .lyric-line').forEach((el,i)=>{
    const idx=parseInt(el.dataset.idx);
    const isActive=idx===active;
    el.classList.toggle('active',isActive);
    // Per-word highlighting: mark words with timestamp <= current time
    if(lyricMode==='karaoke'||isActive){
      el.querySelectorAll('.word').forEach(w=>{
        const wt=parseFloat(w.dataset.ts||0);
        w.classList.toggle('sung',wt<=t);
      });
    }
  });
  const activeEl=document.querySelector('#lyricLines .lyric-line.active');
  if(activeEl) activeEl.scrollIntoView({block:'center',behavior:'smooth'});
  drawVinyl(t);
}
function switchLyricMode(mode){lyricMode=mode;renderLyrics();saveSetting('lyricMode',mode)}
function changeLyricColor(c){
  document.documentElement.style.setProperty('--accent',c);
  document.documentElement.style.setProperty('--accent2',c);
  saveSetting('theme',c);
}
function toggleLyrics(){
  $('lyricsPanel').classList.toggle('active');
  $('lyricBtn').classList.toggle('active');
  if($('lyricsPanel').classList.contains('active')) drawVinyl(A.currentTime);
}
function drawVinyl(t){
  const c=$('lyricCanvas'),ctx=c.getContext('2d'),w=300,h=300;
  ctx.clearRect(0,0,w,h);
  ctx.beginPath();ctx.arc(150,150,140,0,Math.PI*2);
  ctx.fillStyle='#1a1a1a';ctx.fill();
  const img=$('vinylImg');
  if(img.src&&img.complete){
    ctx.save();ctx.beginPath();ctx.arc(150,150,130,0,Math.PI*2);ctx.clip();
    ctx.drawImage(img,20,20,260,260);ctx.restore();
  }
  const angle=(t*0.5)%(Math.PI*2);
  ctx.beginPath();ctx.arc(150,150,8,0,Math.PI*2);ctx.fillStyle='#333';ctx.fill();
  const accent=getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()||'#fa586a';
  ctx.beginPath();ctx.arc(150,150,4,0,Math.PI*2);ctx.fillStyle=accent;ctx.fill();
  for(let r=30;r<130;r+=18){
    ctx.beginPath();ctx.arc(150,150,r,angle,angle+Math.PI*1.8);ctx.strokeStyle='rgba(255,255,255,.08)';ctx.lineWidth=.5;ctx.stroke();
  }
}

// ═══════════════════════════════════════════════
//  播放列表
// ═══════════════════════════════════════════════
async function loadPlaylists(){
  try{
    const r=await fetch('/api/playlists'),d=await r.json();
    const list=$('playlistList'),html=d.playlists.map(p=>
      `<div class="playlist-item" data-name="${p}" onclick="openPlaylist('${p}')" oncontextmenu="ctxPlaylist(event,'${p}')">
        <span class="pl-icon">📋</span><span>${p}</span>
      </div>`
    ).join('');
    list.innerHTML=html||'<div style="padding:12px;color:var(--sub);font-size:12px;text-align:center">还没有播放列表</div>';
  }catch(e){}
}
async function showCreateModal(){$('createInput').value='';$('createModal').classList.add('active');$('createInput').focus()}
async function doCreate(){
  const name=$('createInput').value.trim();if(!name)return;
  $('createModal').classList.remove('active');
  try{const r=await fetch(`/api/playlists?name=${encodeURIComponent(name)}`,{method:'POST'});const d=await r.json();
    if(d.success){toast('创建成功');loadPlaylists()}else toast(d.message,'warn')
  }catch(e){toast('创建失败','warn')}
}
function ctxPlaylist(e,name){e.preventDefault();ctxTarget=name;
  const m=$('ctxMenu');m.style.left=e.clientX+'px';m.style.top=e.clientY+'px';m.classList.add('show');
  document.addEventListener('click',()=>m.classList.remove('show'),{once:true});
}
function ctxRename(){const m=$('ctxMenu');m.classList.remove('show');if(!ctxTarget)return;
  $('renameInput').value=ctxTarget;$('renameModal').classList.add('active');$('renameInput').focus();
}
async function doRename(){
  const nn=$('renameInput').value.trim();if(!nn||nn===ctxTarget){$('renameModal').classList.remove('active');return}
  try{
    const r=await fetch(`/api/playlists/${ctxTarget}?new_name=${encodeURIComponent(nn)}`,{method:'PUT'});const d=await r.json();
    $('renameModal').classList.remove('active');
    if(d.success){loadPlaylists();if($('content').dataset.view==='playlist-'+ctxTarget)openPlaylist(d.name)}else toast(d.message,'warn')
  }catch(e){toast('重命名失败','warn')}
}
async function ctxDelete(){const m=$('ctxMenu');m.classList.remove('show');if(!ctxTarget||!confirm(`确定删除「${ctxTarget}」？`))return;
  try{await fetch(`/api/playlists/${ctxTarget}`,{method:'DELETE'});toast('已删除');loadPlaylists();
    if($('content').dataset.view==='playlist-'+ctxTarget)switchView('search');
  }catch(e){toast('删除失败','warn')}
}
async function openPlaylist(name){
  try{
    const r=await fetch(`/api/playlists/${name}`),d=await r.json();
    if(!d.success){toast(d.message,'warn');return}
    $('content').dataset.view='playlist-'+name;
    document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
    if(!d.songs.length){
      $('content').innerHTML=`<div class="section-title">${d.name}</div><div class="empty"><div class="empty-icon">📋</div><div class="empty-title">播放列表为空</div><div class="empty-sub">搜索歌曲后点击 ＋ 添加</div></div>`;
      return;
    }
    let html=`<div class="section-title">${d.name}</div><div class="song-list-header"><span></span><span></span><span>专辑</span><span style="text-align:center">⏱</span><span></span></div>`;
    d.songs.forEach((s,i)=>{
      html+=`<div class="song-row" ondblclick="playPlaylistSong('${name}',${i})">
        <span class="idx">${i+1}</span>
        <div class="info" onclick="playPlaylistSong('${name}',${i})">
          <img src="${s.cover||''}" onerror="this.style.display='none'" loading="lazy">
          <div class="meta"><div class="t">${esc(s.name)}</div><div class="a">${esc(s.singer)}</div></div>
        </div>
        <span class="album">${esc(s.album)}</span>
        <span class="dur">${fmtTime(s.interval)}</span>
        <span class="actions">          <button onclick="event.stopPropagation();toggleFavorite('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.album)}','${escJs(s.cover)}',${s.interval})" title="收藏">♥</button>          <button onclick="event.stopPropagation();removeFromPlaylist('${name}','${s.mid}')" title="移除">✕</button>
          <button onclick="event.stopPropagation();downloadSong('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.album)}','${escJs(s.cover)}')" title="下载">⬇</button>
        </span>
      </div>`;
    });
    $('content').innerHTML=html;
    // Store playlist data for play
    window._playlistData=d.songs;
  }catch(e){toast('加载失败','warn')}
}
function playPlaylistSong(name,i){
  const s=window._playlistData[i];if(!s)return;
  playlist=window._playlistData.slice();idx=i;
  playSong(s.mid,s.name,s.singer,s.cover,s.interval);
  addHistory(s.mid,s.name,s.singer,s.album||'',s.cover,s.interval);
}
function addToPlaylistPrompt(mid,name,singer,album,cover,interval){
  // Simple: add to a default playlist or show a quick selector
  fetch('/api/playlists').then(r=>r.json()).then(d=>{
    if(!d.playlists.length){toast('请先创建播放列表','warn');return}
    // Add to first playlist for now - could be improved with a selector
    const pl=d.playlists[0];
    fetch(`/api/playlists/${pl}/add?mid=${mid}&song_name=${encodeURIComponent(name)}&singer=${encodeURIComponent(singer)}&album=${encodeURIComponent(album)}&cover=${encodeURIComponent(cover)}&interval=${interval}`,{method:'POST'})
      .then(r=>r.json()).then(d=>{if(d.success)toast(`已添加到「${pl}」`);else toast(d.message,'warn')});
  });
}
async function removeFromPlaylist(name,mid){
  try{
    const r=await fetch(`/api/playlists/${name}/remove?mid=${mid}`,{method:'POST'});const d=await r.json();
    if(d.success){toast('已移除');openPlaylist(name)}else toast(d.message,'warn')
  }catch(e){toast('移除失败','warn')}
}

// ═══════════════════════════════════════════════
//  下载 & 本地库
// ═══════════════════════════════════════════════
async function downloadSong(mid,name,singer,album,cover){
  toast('开始下载…','info');
  try{
    const r=await fetch(`/api/download?mid=${mid}&quality=${Q()}&name=${encodeURIComponent(name)}&singer=${encodeURIComponent(singer)}&album=${encodeURIComponent(album)}&cover=${encodeURIComponent(cover)}`);
    const d=await r.json();toast(d.message,d.success?'':'warn');
  }catch(e){toast('下载失败','warn')}
}
async function loadDownloads(){
  try{
    const r=await fetch('/api/downloads'),d=await r.json();
    if(!d.files.length){$('content').innerHTML='<div class="empty"><div class="empty-icon">📥</div><div class="empty-title">还没有下载的歌曲</div></div>';return}
    let html='<div class="section-title">本地音乐库</div><div class="song-list-header"><span></span><span>文件名</span><span>大小</span><span>时间</span><span></span></div>';
    d.files.forEach(f=>{
      html+=`<div class="song-row">
        <span class="idx">🎵</span>
        <div class="info"><div class="meta"><div class="t">${esc(f.filename)}</div><div class="a">${f.size_mb} MB</div></div></div>
        <span class="album">-</span><span class="dur">${f.time}</span>
        <span class="actions">
          <button onclick="deleteFile('${escJs(f.filename)}')" title="删除">🗑</button>
          <button onclick="openFolder()" title="打开文件夹">📂</button>
        </span>
      </div>`;
    });
    $('content').innerHTML=html;
  }catch(e){}
}
async function deleteFile(name){if(!confirm(`删除 ${name}？`))return;
  try{await fetch(`/api/delete-download?filename=${encodeURIComponent(name)}`);toast('已删除');loadDownloads()}catch(e){toast('删除失败','warn')}
}
async function openFolder(){await fetch('/api/open-folder');toast('已打开下载文件夹','info')}

// ═══════════════════════════════════════════════
//  收藏夹 (我喜欢)
// ═══════════════════════════════════════════════
async function toggleFavorite(mid, name, singer, album, cover, interval) {
  try {
    const r = await fetch(`/api/favorites/toggle?mid=${mid}&name=${encodeURIComponent(name)}&singer=${encodeURIComponent(singer)}&album=${encodeURIComponent(album)}&cover=${encodeURIComponent(cover)}&interval=${interval}`, {method: 'POST'});
    const d = await r.json();
    if (d.success) {
      toast(d.action === 'added' ? '已收藏' : '已取消收藏');
      // 如果正在播放的恰好是这首歌，同步更新底下控制栏的心形
      if(currentSong && currentSong.mid === mid) {
         checkCurrentFavorite(mid);
      }
      // 如果当前播放的视图正是“我喜欢”，或者要更新心形的UI，这里可以触发重载
      if (document.querySelector('.nav-item.active')?.dataset.view === 'favorites') {
         // 我们可以在左侧加一个 "我喜欢" 的专属菜单，或者复用 openPlaylist('我喜欢')
         openPlaylist('我喜欢');
      }
    }
  } catch(e) { toast('操作失败', 'warn') }
}

async function checkCurrentFavorite(mid) {
  try {
    const uid = window.currentUid || 'guest';
    const r = await fetch(`/api/favorites/check?uid=${uid}&mid=${mid}`);
    const d = await r.json();
    const btn = $('npFavBtn');
    btn.style.display = 'inline-block';
    if(d.is_favorite) {
      btn.textContent = '♥'; btn.style.color = 'var(--accent)';
    } else {
      btn.textContent = '♡'; btn.style.color = 'var(--sub)';
    }
  } catch(e) {}
}

async function toggleNpFav() {
  if(!currentSong) return;
  const uid = window.currentUid || 'guest';
  // 乐观UI更新
  const btn = $('npFavBtn');
  const isOk = btn.textContent === '♥';
  btn.textContent = isOk ? '♡' : '♥';
  btn.style.color = isOk ? 'var(--sub)' : 'var(--accent)';
  // 发送API
  toggleFavorite(currentSong.mid, currentSong.name, currentSong.singer, currentSong.album||'', currentSong.cover, currentSong.interval);
}

// ═══════════════════════════════════════════════
//  历史
// ═══════════════════════════════════════════════
async function addHistory(mid,name,singer,album,cover,interval){
  try{await fetch(`/api/history?mid=${mid}&name=${encodeURIComponent(name)}&singer=${encodeURIComponent(singer)}&album=${encodeURIComponent(album)}&cover=${encodeURIComponent(cover)}&interval=${interval}`,{method:'POST'})}catch(e){}
}
async function loadRecent(){
  try{
    const r=await fetch('/api/history'),d=await r.json();
    if(!d.recent.length){$('content').innerHTML='<div class="empty"><div class="empty-icon">🕐</div><div class="empty-title">还没有播放记录</div></div>';return}
    let html='<div class="section-title">最近播放</div><div class="song-list-header"><span></span><span></span><span>歌手</span><span style="text-align:center">⏱</span><span></span></div>';
    d.recent.forEach(s=>{
      html+=`<div class="song-row" ondblclick="playSong('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.cover)}',${s.interval})">
        <span class="idx">🕐</span>
        <div class="info" onclick="playSong('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.cover)}',${s.interval})">
          <img src="${s.cover||''}" onerror="this.style.display='none'" loading="lazy">
          <div class="meta"><div class="t">${esc(s.name)}</div><div class="a">${esc(s.singer)}</div></div>
        </div>
        <span class="album">${esc(s.singer)}</span>
        <span class="dur">${fmtTime(s.interval)}</span>
        <span class="actions">
          <button onclick="event.stopPropagation();toggleFavorite('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','${escJs(s.album)}','${escJs(s.cover)}',${s.interval})" title="收藏">♥</button>
          <button onclick="event.stopPropagation();downloadSong('${s.mid}','${escJs(s.name)}','${escJs(s.singer)}','','${escJs(s.cover)}')" title="下载">⬇</button>
        </span>
      </div>`;
    });
    $('content').innerHTML=html;
  }catch(e){}
}

// ═══════════════════════════════════════════════
//  封面上传
// ═══════════════════════════════════════════════
async function uploadCover(){
  const file=$('coverInput').files[0];if(!file||!currentSong)return;
  const fd=new FormData();fd.append('file',file);
  try{
    const r=await fetch(`/api/covers/upload/${currentSong.mid}`,{method:'POST',body:fd}),d=await r.json();
    if(d.success){
      const url=d.url+'?t='+Date.now();
      $('npCover').src=url;$('vinylImg').src=url;toast('封面已更新');
    }else toast(d.message,'warn')
  }catch(e){toast('上传失败','warn')}
}

// ═══════════════════════════════════════════════
//  登录
// ═══════════════════════════════════════════════
async function checkLogin(){
  try{const r=await fetch('/api/login/check'),d=await r.json();
    if(d.logged_in){$('loginBtn').textContent='👤 已登录';$('loginBtn').classList.add('logged-in')}
  }catch(e){}
}
async function showLogin(){
  $('loginModal').classList.add('active');
  $('qrMsg').textContent='正在获取二维码…';
  try{
    const r=await fetch('/api/login/qrcode'),d=await r.json();
    if(d.success&&d.img){
      $('qrImg').src=d.img;$('qrImg').style.display='';$('qrMsg').textContent='请使用 QQ 扫描二维码';
      pollLogin();
    }else{$('qrMsg').textContent=d.message||'扫码登录暂不可用，请手动放置 credential.json'}
  }catch(e){$('qrMsg').textContent='扫码登录暂不可用'}
}
let _pollTimer=null;
async function pollLogin(){
  if(_pollTimer)clearInterval(_pollTimer);
  _pollTimer=setInterval(async()=>{
    try{
      const r=await fetch('/api/login/status'),d=await r.json();
      if(d.status==='done'){$('qrMsg').textContent='✅ 登录成功！';setTimeout(()=>{$('loginModal').classList.remove('active');checkLogin()},1000);clearInterval(_pollTimer);return}
      if(d.status==='scanned'){$('qrMsg').textContent='📱 已扫描，请在手机上确认';return}
      if(d.status==='confirmed'){$('qrMsg').textContent='✅ 已确认，正在登录…';return}
      if(d.status==='expired'){$('qrMsg').textContent='⏰ 二维码已过期，请重新获取';clearInterval(_pollTimer);return}
      if(d.status==='refused'){$('qrMsg').textContent='❌ 已取消登录';clearInterval(_pollTimer);return}
      if(d.status==='error'){$('qrMsg').textContent='❌ '+d.message;clearInterval(_pollTimer);return}
    }catch(e){}
  },2000);
  setTimeout(()=>{clearInterval(_pollTimer);$('qrMsg').textContent='⏰ 超时，请重试'},120000);
}

// ═══════════════════════════════════════════════
//  设置
// ═══════════════════════════════════════════════
async function loadSettings(){
  try{
    const r=await fetch('/api/settings'),d=await r.json();
    if(d.quality) $('quality').value=d.quality;
    if(d.lyricMode){lyricMode=d.lyricMode;$('lyricModeSel').value=d.lyricMode}
    if(d.theme){document.documentElement.style.setProperty('--accent',d.theme);document.documentElement.style.setProperty('--accent2',d.theme);$('lyricColor').value=d.theme}
  }catch(e){}
}
async function saveSetting(key,value){
  try{await fetch(`/api/settings?key=${key}&value=${encodeURIComponent(JSON.stringify(value))}`,{method:'POST'})}catch(e){}
}
$('quality').addEventListener('change',()=>saveSetting('quality',$('quality').value));
$('lyricModeSel').addEventListener('change',function(){saveSetting('lyricMode',this.value)});

// ═══════════════════════════════════════════════
//  快捷键
// ═══════════════════════════════════════════════
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT')return;
  if(e.code==='Space'){e.preventDefault();togglePlay()}
  if(e.code==='ArrowLeft')A.currentTime-=5;
  if(e.code==='ArrowRight')A.currentTime+=5;
  if(e.code==='KeyL')toggleLyrics();
});

// ═══════════════════════════════════════════════
//  初始化
// ═══════════════════════════════════════════════
loadPlaylists();loadSettings();checkLogin();
setInterval(loadPlaylists,30000); // 每 30s 刷新播放列表
