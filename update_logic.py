import re
with open('d:/WestTrailMusic/index.html', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('onclick="playSearchResult(${i})"', '')
text = text.replace('onclick="playPlaylistSong(\'${name}\',${i})"', '')
text = text.replace('onclick="playSong(\'${s.mid}\',\'${escJs(s.name)}\',\'${escJs(s.singer)}\',\'${escJs(s.cover)}\',${s.interval})"', '')

text = text.replace('ondblclick="playSearchResult(${i})"', 'ondblclick="playSearchResult(${i})" onclick="rowClick(\'${s.mid}\')"')
text = text.replace('ondblclick="playPlaylistSong(\'${name}\',${i})"', 'ondblclick="playPlaylistSong(\'${name}\',${i})" onclick="rowClick(\'${s.mid}\')"')
text = text.replace('ondblclick="playSong(\'${s.mid}\',\'${escJs(s.name)}\',\'${escJs(s.singer)}\',\'${escJs(s.cover)}\',${s.interval})"', 'ondblclick="playSong(\'${s.mid}\',\'${escJs(s.name)}\',\'${escJs(s.singer)}\',\'${escJs(s.cover)}\',${s.interval})" onclick="rowClick(\'${s.mid}\')"')

if 'function rowClick(mid)' not in text:
    text = text.replace('function switchView(view){', 'function rowClick(mid) { if(currentSong && currentSong.mid===mid) togglePlay(); break_selection=true; }\nfunction switchView(view){')

text = text.replace("p.catch(()=>{toast('点击播放按钮开始播放','info')})", "p.catch(()=>{})")

with open('d:/WestTrailMusic/index.html', 'w', encoding='utf-8') as f:
    f.write(text)
