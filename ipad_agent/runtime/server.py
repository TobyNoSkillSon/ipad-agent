#!/usr/bin/env python3
"""Private-LAN display server for the paired iPad."""
from __future__ import annotations

import argparse
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import signal
import threading
import time
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any

from ipad_agent.core.paths import private_mkdir, private_write_text, require_runtime_path

MAX_BODY = 2 * 1024 * 1024


class DisplayState:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.sequence = 0
        self.revision = ""
        self.payload: dict[str, Any] | None = None
        self.published_ns = 0
        self.ready_revision = ""
        self.ready_ns = 0
        self.last_seen_ns = 0
        self.last_peer = ""
        self.visible = False
        self.invalidated = False
        self.resume_mode = "url"
        self.last_error = ""

    def publish(self, payload: dict[str, Any]) -> dict[str, Any]:
        import hashlib
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
        with self.condition:
            self.sequence += 1
            self.revision = f"{self.sequence}-{digest}"
            self.payload = payload
            self.published_ns = time.monotonic_ns()
            self.ready_revision = ""
            self.ready_ns = 0
            self.last_error = ""
            self.condition.notify_all()
            return self.snapshot()

    def acknowledge(self, revision: str, peer: str, ready: bool, visible: bool, error: str = "") -> bool:
        now = time.monotonic_ns()
        with self.condition:
            if revision != self.revision:
                return False
            self.last_seen_ns = now
            self.last_peer = peer
            self.visible = visible
            if error:
                self.last_error = error[:200]
            if ready and visible:
                self.ready_revision = revision
                self.ready_ns = now
            self.condition.notify_all()
            return True

    def mark_hidden(self, resume_mode: str) -> None:
        with self.condition:
            self.visible = False
            self.last_seen_ns = 0
            self.invalidated = True
            self.resume_mode = "app" if resume_mode == "app" else "url"
            self.condition.notify_all()

    def activate(self) -> None:
        with self.condition:
            self.invalidated = False
            self.resume_mode = "url"
            self.condition.notify_all()

    def wait_after(self, revision: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.revision == revision and time.monotonic() < deadline:
                self.condition.wait(max(0.0, deadline - time.monotonic()))
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "revision": self.revision,
            "payload": self.payload,
            "published_ns": self.published_ns,
            "ready_revision": self.ready_revision,
            "ready_ns": self.ready_ns,
            "last_seen_ns": self.last_seen_ns,
            "last_seen_age_ms": ((time.monotonic_ns() - self.last_seen_ns) / 1_000_000) if self.last_seen_ns else None,
            "last_peer": self.last_peer,
            "visible": self.visible,
            "invalidated": self.invalidated,
            "resume_mode": self.resume_mode,
            "last_error": self.last_error,
        }


STATE = DisplayState()
TOKEN = ""
BIND_HOST = ""
RUNTIME_DIR = Path("/tmp")
ASSET_DIR = Path("/tmp")
SERVER: ThreadingHTTPServer | None = None

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark"><title>Now</title>
<link rel="stylesheet" href="/style.css"></head>
<body><div id="connection">Connecting...</div><main id="content" aria-live="polite"></main>
<footer id="meta"></footer><script src="/client.js" defer></script></body></html>"""

STYLE = r""":root{font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;color:#171717;background:#f6f4ef;line-height:1.45}*{box-sizing:border-box}body{margin:0;min-height:100vh;padding:max(30px,env(safe-area-inset-top)) max(42px,env(safe-area-inset-right)) max(30px,env(safe-area-inset-bottom)) max(42px,env(safe-area-inset-left));display:flex;flex-direction:column}main{width:min(1120px,100%);margin:auto;flex:1;display:flex;flex-direction:column;justify-content:center}h1{font-size:clamp(2.2rem,5vw,5rem);line-height:1.04;margin:0 0 .5em;letter-spacing:-.035em}h2{font-size:clamp(1.3rem,2.5vw,2.15rem);margin:1.2em 0 .35em}.text{font-size:clamp(1.25rem,2.2vw,2rem);white-space:pre-wrap;max-width:44em}.quote{font-family:Georgia,serif;font-size:clamp(2rem,4.2vw,4.4rem);line-height:1.22;margin:0;max-width:24em}.source{font-size:clamp(1rem,1.8vw,1.55rem);margin-top:1.4em;color:#5b5b5b}.sections{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}.section{background:rgba(255,255,255,.64);border:1px solid rgba(0,0,0,.1);border-radius:18px;padding:22px}.section h2{margin-top:0}.section p,.section li{font-size:clamp(1rem,1.6vw,1.35rem);white-space:pre-wrap}.section ul{padding-left:1.2em}pre{font-family:"SFMono-Regular",Consolas,monospace;font-size:clamp(.85rem,1.45vw,1.25rem);line-height:1.5;background:#151515;color:#f5f5f5;padding:24px;border-radius:16px;overflow:auto;white-space:pre-wrap}table{width:100%;border-collapse:collapse;font-size:clamp(.9rem,1.5vw,1.25rem);background:rgba(255,255,255,.65)}th,td{padding:13px 15px;border:1px solid rgba(0,0,0,.14);text-align:left}img{display:block;max-width:100%;max-height:78vh;object-fit:contain;margin:auto;border-radius:12px}iframe{width:100%;height:78vh;border:0;border-radius:12px;background:white}video{width:100%;max-height:78vh}footer,#connection{font-size:.8rem;color:#777}footer{padding-top:20px}#connection{position:fixed;top:10px;right:14px}#connection.ok{color:#387b43}#connection.stale{color:#ad4e32}@media(prefers-color-scheme:dark){:root{color:#f1f1ee;background:#161616}.source,footer,#connection{color:#aaa}.section,table{background:rgba(255,255,255,.06);border-color:rgba(255,255,255,.15)}th,td{border-color:rgba(255,255,255,.16)}}"""

CLIENT = r"""(() => {
  const token = decodeURIComponent(location.hash.slice(1));
  const content = document.getElementById("content"), meta = document.getElementById("meta"), connection = document.getElementById("connection");
  let revision = "", current = null;
  const auth = {"Authorization": `Bearer ${token}`};
  const el = (tag, text, cls) => { const node=document.createElement(tag); if(text!==undefined&&text!==null)node.textContent=String(text); if(cls)node.className=cls; return node; };
  const twoFrames = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const mediaReady = node => new Promise(resolve => { if(node.tagName==="IMG"&&node.complete)return resolve(node.naturalWidth>0); let settled=false; const done=ok=>{if(!settled){settled=true;resolve(ok);}}; node.addEventListener("load",()=>done(true),{once:true}); node.addEventListener("error",()=>done(false),{once:true}); setTimeout(()=>done(false),3000); });
  async function ack(ready, visible=document.visibilityState==="visible", error="") { if(!revision)return; try{await fetch("/api/ack",{method:"POST",headers:{...auth,"Content-Type":"application/json"},cache:"no-store",body:JSON.stringify({revision,ready:Boolean(ready)&&visible,visible:Boolean(visible),error:String(error||"")})});}catch(_){} }
  async function render(state) {
    revision=state.revision; current=state; const p=state.payload||{}; content.replaceChildren(); document.title=p.title?`${p.title} - Now`:"Now"; const waits=[];
    if(p.kind==="quote"){if(p.title)content.append(el("h1",p.title));content.append(el("blockquote",p.text||"","quote"));if(p.source)content.append(el("div",p.source,"source"));}
    else if(p.kind==="report"){content.append(el("h1",p.title||"Report"));const grid=el("div",null,"sections");for(const section of(p.sections||[])){const card=el("section",null,"section");if(section.heading)card.append(el("h2",section.heading));if(Array.isArray(section.body)){const list=el("ul");for(const item of section.body)list.append(el("li",item));card.append(list);}else card.append(el("p",section.body||""));grid.append(card);}content.append(grid);}
    else if(p.kind==="code"){content.append(el("h1",p.title||"Code"));content.append(el("pre",p.text||""));}
    else if(p.kind==="table"){content.append(el("h1",p.title||"Data"));const table=el("table"),head=el("thead"),hr=el("tr"),body=el("tbody");for(const col of(p.columns||[]))hr.append(el("th",col));head.append(hr);table.append(head);for(const row of(p.rows||[])){const tr=el("tr");for(const value of row)tr.append(el("td",value));body.append(tr);}table.append(body);content.append(table);}
    else if(p.kind==="file"){content.append(el("h1",p.title||p.name||"File"));let node;if((p.mime||"").startsWith("image/"))node=el("img");else if((p.mime||"")==="application/pdf")node=el("iframe");else if((p.mime||"").startsWith("video/")){node=el("video");node.controls=true;}else{node=el("a","Open file");node.target="_blank";}node.src=p.url;if(node.tagName==="A")node.href=p.url;content.append(node);if(node.tagName!=="A")waits.push(mediaReady(node));if(p.caption)content.append(el("div",p.caption,"source"));}
    else{if(p.title)content.append(el("h1",p.title));content.append(el("div",p.text||"","text"));}
    meta.textContent=`${p.generated||""}  ·  revision ${revision}`;const outcomes=await Promise.all(waits);if(outcomes.some(ok=>ok===false)){connection.textContent="Asset failed to load";connection.className="stale";await ack(false,document.visibilityState==="visible","asset-load-failed");return;}connection.textContent="Current";connection.className="ok";await twoFrames();await ack(true);
  }
  async function loop(){if(!token){connection.textContent="Missing display token";connection.className="stale";return;}for(;;){try{const response=await fetch(`/api/state?after=${encodeURIComponent(revision)}`,{headers:auth,cache:"no-store"});if(!response.ok)throw new Error(String(response.status));const state=await response.json();if(state.revision&&state.revision!==revision)await render(state);}catch(_){connection.textContent="Reconnecting";connection.className="stale";await new Promise(resolve=>setTimeout(resolve,500));}}}
  setInterval(()=>ack(false),2000);
  addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible"){ack(false,true);if(current)render(current);}else ack(false,false);});
  addEventListener("pageshow",()=>{if(current)render(current);});
  loop();
})();"""


def _trusted_peer(value:str)->bool:
    try:address=ipaddress.ip_address(value)
    except ValueError:return False
    if address.is_loopback:return True
    networks=(ipaddress.ip_network("10.0.0.0/8"),ipaddress.ip_network("172.16.0.0/12"),ipaddress.ip_network("192.168.0.0/16"))
    return address.version == 4 and any(address in network for network in networks)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, _format: str, *_args: object) -> None: return
    def _private_peer(self) -> bool:
        try:
            return _trusted_peer(self.client_address[0])
        except ValueError:return False
    def _host_peer(self) -> bool:
        peer=self.client_address[0];return peer==BIND_HOST or peer.startswith("127.")
    def _authorized(self) -> bool:
        supplied=self.headers.get("Authorization","");prefix="Bearer ";return supplied.startswith(prefix) and hmac.compare_digest(supplied[len(prefix):],TOKEN)
    def _send(self,status:int,body:bytes=b"",content_type:str="application/json")->None:
        self.send_response(status);self.send_header("Content-Type",content_type);self.send_header("Content-Length",str(len(body)));self.send_header("Cache-Control","no-store");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Referrer-Policy","no-referrer");self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'");self.end_headers();
        if body:self.wfile.write(body)
    def _send_file(self,target:Path,mime:str)->None:
        size=target.stat().st_size
        self.send_response(HTTPStatus.OK);self.send_header("Content-Type",mime);self.send_header("Content-Length",str(size));self.send_header("Cache-Control","private, max-age=31536000, immutable");self.send_header("X-Content-Type-Options","nosniff");self.send_header("Referrer-Policy","no-referrer");self.end_headers()
        with target.open("rb") as stream:
            shutil.copyfileobj(stream,self.wfile,length=1024*1024)
    def _json(self,status:int,value:object)->None:self._send(status,json.dumps(value,separators=(",",":"),ensure_ascii=False).encode())
    def _body_json(self)->dict[str,Any]|None:
        try:length=int(self.headers.get("Content-Length","0"))
        except ValueError:return None
        if length<0 or length>MAX_BODY:return None
        try:value=json.loads(self.rfile.read(length))
        except (json.JSONDecodeError,UnicodeDecodeError):return None
        return value if isinstance(value,dict) else None
    def do_GET(self)->None:
        parsed=urlparse(self.path)
        if parsed.path in ("/","/now"):self._send(HTTPStatus.OK,PAGE.encode(),"text/html; charset=utf-8");return
        if parsed.path=="/style.css":self._send(HTTPStatus.OK,STYLE.encode(),"text/css; charset=utf-8");return
        if parsed.path=="/client.js":self._send(HTTPStatus.OK,CLIENT.encode(),"application/javascript; charset=utf-8");return
        if parsed.path.startswith("/a/"):
            parts=parsed.path.split("/")
            if not self._private_peer() or len(parts)!=4 or not hmac.compare_digest(unquote(parts[2]),TOKEN):self._send(HTTPStatus.FORBIDDEN);return
            name=unquote(parts[3])
            if Path(name).name!=name:self._send(HTTPStatus.NOT_FOUND);return
            target=(ASSET_DIR/name).resolve()
            if target.parent!=ASSET_DIR.resolve() or not target.is_file():self._send(HTTPStatus.NOT_FOUND);return
            mime=mimetypes.guess_type(name)[0] or "application/octet-stream";self._send_file(target,mime);return
        if not self._authorized() or not self._private_peer():self._send(HTTPStatus.FORBIDDEN);return
        if parsed.path=="/health":self._json(HTTPStatus.OK,{"ok":True,"pid":os.getpid(),"host":BIND_HOST});return
        if parsed.path=="/api/status":
            snapshot=STATE.snapshot();snapshot.pop("payload",None);self._json(HTTPStatus.OK,snapshot);return
        if parsed.path=="/api/state":
            after=parse_qs(parsed.query).get("after",[""])[0];self._json(HTTPStatus.OK,STATE.wait_after(after,20.0));return
        self._send(HTTPStatus.NOT_FOUND)
    def do_POST(self)->None:
        parsed=urlparse(self.path)
        if not self._authorized() or not self._private_peer():self._send(HTTPStatus.FORBIDDEN);return
        body=self._body_json()
        if body is None:self._send(HTTPStatus.BAD_REQUEST);return
        if parsed.path=="/api/hide":
            if not self._host_peer():self._send(HTTPStatus.FORBIDDEN);return
            STATE.mark_hidden(str(body.get("resume") or "url"));self._json(HTTPStatus.OK,{"ok":True});return
        if parsed.path=="/api/activate":
            if not self._host_peer():self._send(HTTPStatus.FORBIDDEN);return
            STATE.activate();self._json(HTTPStatus.OK,{"ok":True});return
        if parsed.path=="/api/show":
            if not self._host_peer():self._send(HTTPStatus.FORBIDDEN);return
            payload=body.get("payload")
            if not isinstance(payload,dict):self._send(HTTPStatus.BAD_REQUEST);return
            self._json(HTTPStatus.OK,STATE.publish(payload));return
        if parsed.path=="/api/ack":
            revision=body.get("revision")
            if not isinstance(revision,str):self._send(HTTPStatus.BAD_REQUEST);return
            accepted=STATE.acknowledge(revision,self.client_address[0],bool(body.get("ready")),bool(body.get("visible")),str(body.get("error") or ""));self._send(HTTPStatus.NO_CONTENT if accepted else HTTPStatus.CONFLICT);return
        if parsed.path=="/api/shutdown":
            if not self._host_peer():self._send(HTTPStatus.FORBIDDEN);return
            self._json(HTTPStatus.OK,{"ok":True});threading.Thread(target=SERVER.shutdown,daemon=True).start();return
        self._send(HTTPStatus.NOT_FOUND)


def atomic_json(path:Path,value:object)->None:
    private_write_text(path, json.dumps(value, separators=(",", ":")))


def _valid_bind_host(value:str)->bool:
    try:address=ipaddress.ip_address(value)
    except ValueError:return False
    networks=(ipaddress.ip_network("10.0.0.0/8"),ipaddress.ip_network("172.16.0.0/12"),ipaddress.ip_network("192.168.0.0/16"),ipaddress.ip_network("169.254.0.0/16"))
    return address.version == 4 and any(address in network for network in networks)


def main()->int:
    global TOKEN,BIND_HOST,RUNTIME_DIR,ASSET_DIR,SERVER
    parser=argparse.ArgumentParser();parser.add_argument("--host",required=True);parser.add_argument("--port",type=int,default=0);parser.add_argument("--runtime-dir",required=True);args=parser.parse_args()
    if not _valid_bind_host(args.host):raise SystemExit("display host must be one reachable private IPv4 address")
    BIND_HOST=args.host;RUNTIME_DIR=private_mkdir(require_runtime_path(args.runtime_dir));ASSET_DIR=private_mkdir(RUNTIME_DIR/"assets")
    token_path=RUNTIME_DIR/"token"
    TOKEN=secrets.token_urlsafe(24)
    private_write_text(token_path,TOKEN)
    SERVER=ThreadingHTTPServer((BIND_HOST,args.port),Handler);SERVER.daemon_threads=True;host,port=SERVER.server_address[:2]
    atomic_json(RUNTIME_DIR/"server.json",{"pid":os.getpid(),"host":host,"port":port,"token":TOKEN,"started_ns":time.monotonic_ns()})
    def stop(_signum:int,_frame:object)->None:threading.Thread(target=SERVER.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:SERVER.serve_forever(poll_interval=.2)
    finally:
        SERVER.server_close();shutil.rmtree(ASSET_DIR,ignore_errors=True);meta=RUNTIME_DIR/"server.json"
        try:
            current=json.loads(meta.read_text())
            if current.get("pid")==os.getpid():meta.unlink()
        except (FileNotFoundError,json.JSONDecodeError,OSError):pass
    return 0

if __name__=="__main__":raise SystemExit(main())
