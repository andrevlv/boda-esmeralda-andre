# Pipeline de publicación — Boda Esmeralda & André (correr en el workbench de Composio)
import re, base64, hashlib, json, io, time, requests, concurrent.futures
from PIL import Image, ImageFilter

OWNER, REPO, BRANCH = "andrevlv", "boda-esmeralda-andre", "main"
SITE = f"https://{OWNER}.github.io/{REPO}/"
FOLDER = "1PCCTKI_YDxzxpcPXPHIlyK73VRP5vx4d"   # Drive: "save the day"
SHEET_ID = "1ECy1EG9Uiik_67zmSjHCn4VeZOidwY7b8kGf8wYG8vo"
EXT = {"image/jpeg":"jpg","image/png":"png","image/webp":"webp","image/gif":"gif","video/mp4":"mp4","video/webm":"webm",
       "audio/mp4":"m4a","audio/mpeg":"mp3","audio/webm":"weba","font/woff2":"woff2","font/ttf":"ttf"}
PART = 2_500_000

def _d(r):
    d = (r or {}).get("data", r)
    while isinstance(d, dict) and "data" in d and isinstance(d["data"], dict) and len(d) <= 3: d = d["data"]
    return d

def gh(method, ep, body=None):
    r, e = proxy_execute(method, ep, "github", body=body)
    if e: raise Exception(f"{method} {ep}: {e}")
    return r

def latest_html():
    r, e = run_composio_tool("GOOGLEDRIVE_FIND_FILE", {"folder_id": FOLDER,
        "q": "name contains 'invitacion' and name contains '.html' and trashed = false", "orderBy": "modifiedTime desc",
        "fields": "files(id,name,modifiedTime,size)"})
    if e: raise Exception(e)
    files = _d(r).get("files", [])
    if not files: raise Exception("No hay .html 'invitacion' en la carpeta de Drive")
    return files[0]

def download(fid):
    r, e = run_composio_tool("GOOGLEDRIVE_DOWNLOAD_FILE", {"fileId": fid})
    if e: raise Exception(e)
    c = _d(r).get("downloaded_file_content") or {}
    return requests.get(c.get("s3url") or c.get("url"), timeout=170).content.decode("utf-8")

def make_og(png_bytes):
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB"); W, H = im.size
    y0, y1 = int(H*0.195), int(H*0.56)
    crop = im.crop((0, y0, W, y1)); w = int(crop.width * 630 / crop.height); crop = crop.resize((w, 630), Image.LANCZOS)
    bg = im.crop((0, y0, W, y1)).resize((1200, int(1200*(y1-y0)/W)), Image.LANCZOS)
    t = (bg.height - 630)//2; bg = bg.crop((0, max(0,t), 1200, max(0,t)+630)).filter(ImageFilter.GaussianBlur(22))
    bg.paste(crop, ((1200 - w)//2, 0))
    b = io.BytesIO(); bg.save(b, "JPEG", quality=84, optimize=True, progressive=True); og = b.getvalue()
    s = int(W*0.30); cx, cy = int(W*0.524), int(H*0.474)
    ic = im.crop((cx-s//2, cy-s//2, cx+s//2, cy+s//2)).resize((180,180), Image.LANCZOS)
    b2 = io.BytesIO(); ic.save(b2, "PNG", optimize=True)
    return og, b2.getvalue()

RSVP_JS = """<script>(function(){
var DEV='';
try{ DEV=localStorage.getItem('rsvp-dev')||''; if(!DEV){ DEV=Math.random().toString(36).slice(2)+Date.now().toString(36); localStorage.setItem('rsvp-dev',DEV);} }catch(e){ DEV='nodev'; }
var cfgP=fetch('config.json?t='+Date.now(),{cache:'no-store'}).then(function(r){return r.json()}).catch(function(){return null});
window.__rsvpSend=function(name){ cfgP.then(function(c){ if(!c||!c.endpoint) return;
  var body=JSON.stringify({action:'rsvp',name:name,device:DEV,ua:navigator.userAgent,lang:navigator.language,tz:(Intl.DateTimeFormat().resolvedOptions().timeZone||''),ts:Date.now()});
  try{ if(navigator.sendBeacon && navigator.sendBeacon(c.endpoint,new Blob([body],{type:'text/plain'}))) return; }catch(e){}
  fetch(c.endpoint,{method:'POST',mode:'no-cors',headers:{'Content-Type':'text/plain'},body:body}).catch(function(){});
}); };
window.__rsvpRemote=function(){ return cfgP.then(function(c){ if(!c||!c.endpoint) return null;
  return fetch(c.endpoint+(c.endpoint.indexOf('?')<0?'?':'&')+'action=count&t='+Date.now()).then(function(r){return r.json()}).then(function(j){ return (j&&typeof j.total==='number')?j.total:null; }).catch(function(){ return null; }); }); };
})();</script>"""

LIVE_JS = """<script>(function(){var V='%s';if(!/github\\.io$/.test(location.hostname))return;
function chk(){fetch('version.json?t='+Date.now(),{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
if(j&&j.v&&j.v!==V&&!document.getElementById('upd')){var d=document.createElement('button');d.id='upd';d.type='button';
d.textContent='✨ Actualizamos la invitación · toca para ver';d.setAttribute('style','position:fixed;top:14px;left:50%%;transform:translateX(-50%%);z-index:400;border:none;cursor:pointer;padding:11px 18px;border-radius:24px;background:#8F3E1F;color:#FFFDF9;font:16px Georgia,serif;box-shadow:0 10px 26px -8px rgba(0,0,0,.4)');
d.onclick=function(){location.reload()};document.body.appendChild(d);}}).catch(function(){})}
setInterval(chk,60000);document.addEventListener('visibilitychange',function(){if(!document.hidden)chk()});})();</script>"""

def build(html):
    for p in [r'<style id="edStyles">.*?</style>', r'<div id="edBar">.*?</div>\s*<div id="edToast"[^>]*>[^<]*</div>', r'<script id="edScript">.*?</script>']:
        html = re.sub(p, "", html, count=1, flags=re.S)
    html = re.sub(r'<div id="ed(?:Video|Plate|Gallery)Tools"[^>]*>.*?</div>', "", html, flags=re.S)
    html = re.sub(r'\s*<div class="ed-tools">(?:(?!</div>).)*</div>', "", html, flags=re.S)
    html = html.replace('<button type="button" class="ed-del">×</button>', "").replace(' data-ed="text"', "")
    html = re.sub(r'\s(?:src)="blob:[^"]*"', "", html)
    html = html.replace("async function computeConfirmedTotal(){",
        "async function computeConfirmedTotal(){\n    if (window.__rsvpRemote){ try{ const t = await window.__rsvpRemote(); if (typeof t === 'number') return t; }catch(e){} }", 1)
    html = html.replace("await storeSet('rsvp:' + slug(name), JSON.stringify(data), true);",
        "await storeSet('rsvp:' + slug(name), JSON.stringify(data), true);\n    if (window.__rsvpSend) window.__rsvpSend(name);", 1)
    k = html.index("<script>"); html = html[:k] + RSVP_JS + "\n" + html[k:]
    assets, seen = {}, {}
    def rep(m):
        mime, b = m.group(1), m.group(2)
        if b in seen: return seen[b]
        raw = base64.b64decode(b)
        name = "assets/" + hashlib.sha1(raw).hexdigest()[:12] + "." + EXT.get(mime, "bin")
        assets[name] = raw; seen[b] = name; return name
    html = re.sub(r'data:([\w/+.\-]+);base64,([A-Za-z0-9+/=]+)', rep, html)
    m = re.search(r'<img class="intro-still" src="([^"]+)"', html)
    if m and m.group(1) in assets:
        assets["og.jpg"], assets["icon.png"] = make_og(assets[m.group(1)])
    ver = str(int(time.time()))
    meta = f"""<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Esmeralda &amp; André — 4 de diciembre</title>
<meta name="description" content="Nos casamos el 4 de diciembre de 2026 en Arequipa. Abre nuestra invitación y confirma tu asistencia.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Esmeralda &amp; André">
<meta property="og:title" content="Esmeralda &amp; André · Nos casamos">
<meta property="og:description" content="4 de diciembre de 2026 · Arequipa, Perú. Toca para abrir la invitación ✨">
<meta property="og:url" content="{SITE}">
<meta property="og:image" content="{SITE}og.jpg?v={ver}">
<meta property="og:image:secure_url" content="{SITE}og.jpg?v={ver}">
<meta property="og:image:type" content="image/jpeg">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="Sobre de la invitación de boda de Esmeralda y André">
<meta property="og:locale" content="es_PE">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#E9DCC8">
<link rel="icon" href="icon.png?v={ver}">
<link rel="apple-touch-icon" href="icon.png?v={ver}">
<link rel="canonical" href="{SITE}">
"""
    html = re.sub(r'<meta charset="UTF-8">\s*', "", html, count=1)
    html = re.sub(r'<meta name="viewport"[^>]*>\s*', "", html, count=1)
    html = re.sub(r'<title>.*?</title>\s*', "", html, count=1, flags=re.S)
    html = html.replace("<head>", "<head>\n" + meta, 1)
    k = html.rindex("</body>"); html = html[:k] + (LIVE_JS % ver) + "\n" + html[k:]
    files = {"index.html": html.encode("utf-8"), "version.json": json.dumps({"v": ver}).encode(), ".nojekyll": b""}
    files.update(assets)
    return files, ver

def split_large(files):
    out, manifest = {}, []
    for path, data in files.items():
        if len(data) <= PART: out[path] = data; continue
        names = []
        for i in range(0, len(data), PART):
            n = path.replace("/", "__") + f".{i//PART:03d}"; out["_parts/" + n] = data[i:i+PART]; names.append(n)
        manifest.append(path + "|" + " ".join(names))
    if manifest: out["_parts/manifest.txt"] = ("\n".join(manifest) + "\n").encode()
    return out

def publish(files, msg):
    files = split_large(files)
    base = gh("GET", f"/repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")["object"]["sha"]
    bc = gh("GET", f"/repos/{OWNER}/{REPO}/git/commits/{base}")
    keep = gh("GET", f"/repos/{OWNER}/{REPO}/git/trees/{bc['tree']['sha']}?recursive=1")
    KEEP = (".github/", "tools/")
    tree = [{"path": t["path"], "mode": t["mode"], "type": "blob", "sha": t["sha"]} for t in keep.get("tree", [])
            if t["type"] == "blob" and (t["path"].startswith(KEEP) or t["path"] in ("README.md", "config.json")) and t["path"] not in files]
    def mk(item):
        p, d = item
        return p, gh("POST", f"/repos/{OWNER}/{REPO}/git/blobs", {"content": base64.b64encode(d).decode(), "encoding": "base64"})["sha"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for p, s in ex.map(mk, sorted(files.items(), key=lambda kv: -len(kv[1]))):
            tree.append({"path": p, "mode": "100644", "type": "blob", "sha": s})
    t = gh("POST", f"/repos/{OWNER}/{REPO}/git/trees", {"tree": tree})
    c = gh("POST", f"/repos/{OWNER}/{REPO}/git/commits", {"message": msg, "tree": t["sha"], "parents": [base]})
    gh("PATCH", f"/repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}", {"sha": c["sha"], "force": False})
    return c["sha"], len(files)

def set_endpoint(url):
    body = {"message": "Conectar confirmaciones a Google Sheets", "content": base64.b64encode(json.dumps({"endpoint": url}).encode()).decode()}
    try:
        cur, _ = proxy_execute("GET", f"/repos/{OWNER}/{REPO}/contents/config.json", "github")
        if cur and cur.get("sha"): body["sha"] = cur["sha"]
    except Exception: pass
    return gh("PUT", f"/repos/{OWNER}/{REPO}/contents/config.json", body)

def full_publish(msg="Actualizar invitación", html=None, name="manual"):
    if html is None:
        f = latest_html(); html = download(f["id"]); name = f["name"]
    files, ver = build(html)
    sha, n = publish(files, f"{msg} · {name}")
    return name, sha, n
