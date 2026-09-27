"""Local web UI (roadmap decisions 4 and 10): `screen-context ui`.

A separate process from `serve`, bound to 127.0.0.1 on a random port. This is the user path: it
may write, and it audits every opening and every write. It never imports capture code.

Session security:
- The launch URL carries a one-time token, valid for 2 minutes. Opening it exchanges the token
  for a random session ID in an HttpOnly, SameSite=Strict cookie, then redirects to a URL
  without the token.
- Every request must name this server in Host (DNS rebinding). A write must also be a POST from
  this server's Origin with a JSON body, and must repeat a confirmation nonce that the server
  issued for that action in this session. No CORS headers are ever sent.
- A session ends after 5 minutes without a request from the user, and at once when the screen
  locks. When no session and no launch token are left, the process exits; run
  `screen-context ui` again.
"""
import hashlib
import html
import secrets
import sys
import threading
import time
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route
from . import audit
from .health import screen_locked
from .i18n import resolve, t

IDLE = 300
LAUNCH_TTL = 120
CONFIRM_TTL = 60
COOKIE = "sc_ui"
CLIENT = "ui"
SECURITY_HEADERS = [(k.encode(), v.encode()) for k, v in {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
                               "img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}.items()]


def digest(value): return hashlib.sha256(value.encode()).hexdigest()


class Sessions:
    """Launch tokens, sessions and confirmation nonces, kept only as digests in memory."""
    def __init__(self, idle=IDLE, locked=screen_locked, clock=time.monotonic, on_end=None):
        self.idle, self.locked, self.clock = idle, locked, clock
        self.on_end = on_end or (lambda reason: None)
        self.guard = threading.Lock()
        self.launches, self.sessions, self.confirms = {}, {}, {}

    def launch_token(self):
        token = secrets.token_urlsafe(32)
        with self.guard: self.launches[digest(token)] = self.clock() + LAUNCH_TTL
        return token

    def exchange(self, token):
        """A new session ID for an unused, unexpired launch token; None otherwise."""
        if not token or self.locked(): return None
        with self.guard:
            expires = self.launches.pop(digest(token), None)
            if expires is None or self.clock() > expires: return None
            sid = secrets.token_urlsafe(32)
            self.sessions[digest(sid)] = self.clock()
        return sid

    def check(self, sid, touch=True):
        """True for a live session. `touch` counts the request as activity; the page's own
        polling does not, so an open but unused tab still expires."""
        if not sid: return False
        key, locked = digest(sid), self.locked()
        with self.guard:
            last = self.sessions.get(key)
            if last is None: return False
            reason = "locked" if locked else "idle" if self.clock() - last > self.idle else None
            if reason is None:
                if touch: self.sessions[key] = self.clock()
                return True
            self._drop(key)
        self.on_end(reason)
        return False

    def confirm(self, sid, action):
        nonce = secrets.token_urlsafe(16)
        with self.guard: self.confirms[digest(nonce)] = (digest(sid), action, self.clock() + CONFIRM_TTL)
        return nonce

    def redeem(self, sid, action, nonce):
        """Use a confirmation nonce once; it must belong to this session and this action."""
        if not nonce or not isinstance(nonce, str): return False
        with self.guard: entry = self.confirms.pop(digest(nonce), None)
        return entry is not None and entry[:2] == (digest(sid), action) and self.clock() <= entry[2]

    def sweep(self):
        """End idle sessions, and everything when the screen locks. False once nothing is left."""
        locked = self.locked()
        with self.guard:
            now = self.clock()
            ended = [k for k, last in self.sessions.items() if locked or now - last > self.idle]
            for key in ended: self._drop(key)
            self.launches = {k: e for k, e in self.launches.items() if not locked and now <= e}
            alive = bool(self.sessions or self.launches)
        for _ in ended: self.on_end("locked" if locked else "idle")
        return alive

    def _drop(self, key):  # the caller holds the guard
        del self.sessions[key]
        self.confirms = {n: c for n, c in self.confirms.items() if c[0] != key}


def set_paused(settings, paused):
    flag = settings.root / "paused"
    if paused: flag.touch(mode=0o600)
    else: flag.unlink(missing_ok=True)
    return {"paused": paused}


# Writes the UI offers: action -> (confirmation text key, function of settings returning audit params).
WRITES = {
    "pause": ("ui.confirm.pause", lambda settings: set_paused(settings, True)),
    "resume": ("ui.confirm.resume", lambda settings: set_paused(settings, False)),
}


class Guard:
    """Refuse requests for any other Host, and add the security headers to every response."""
    def __init__(self, app, hosts):
        self.app, self.hosts = app, hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if dict(scope["headers"]).get(b"host", b"").decode("latin-1") not in self.hosts:
            await PlainTextResponse("Unknown host", status_code=421)(scope, receive, send)
            return
        async def secured(message):
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *SECURITY_HEADERS]
            await send(message)
        await self.app(scope, receive, secured)


def shell(lang, body, status=200):
    title = html.escape(t("ui.title", lang))
    return HTMLResponse(f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
                        f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>'
                        f'<link rel="stylesheet" href="/ui.css"></head>{body}</html>', status_code=status)


def notice(lang, key, status):
    return shell(lang, f'<body><main><h1>{html.escape(t("ui.title", lang))}</h1><p>{html.escape(t(key, lang))}</p></main></body>', status)


def home(settings, lang):
    e = lambda key: html.escape(t(key, lang), quote=True)
    paused = (settings.root / "paused").exists()
    action = "resume" if paused else "pause"
    return shell(lang, f'<body data-expired="{e("ui.expired")}" data-failed="{e("ui.failed")}"><main>'
                       f'<h1>{e("ui.title")}</h1>'
                       f'<p id="status">{e("ui.status.paused" if paused else "ui.status.recording")}</p>'
                       f'<button type="button" data-action="{action}">{e("ui." + action)}</button>'
                       f'<p id="message" role="status"></p>'
                       f'<p class="note">{e("ui.session")}</p>'
                       f'</main><script src="/ui.js"></script></body>')


SCRIPT = """\
const main = document.querySelector("main"), data = document.body.dataset;
let timer;
function ended() {
  clearInterval(timer);
  const p = document.createElement("p");
  p.textContent = data.expired;
  main.replaceChildren(main.querySelector("h1"), p);
}
async function post(action, body) {
  const r = await fetch("/api/" + action, {method: "POST", credentials: "same-origin",
    headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (r.status === 401) { ended(); return null; }
  return {ok: r.ok, json: await r.json().catch(() => ({}))};
}
for (const button of document.querySelectorAll("button[data-action]")) {
  button.addEventListener("click", async () => {
    const message = document.getElementById("message"), action = button.dataset.action;
    const ask = await post(action, {});
    if (!ask) return;
    if (!ask.ok || !ask.json.confirm) { message.textContent = data.failed; return; }
    if (!window.confirm(ask.json.message)) return;
    const done = await post(action, {confirm: ask.json.confirm});
    if (!done) return;
    if (done.ok) location.reload(); else message.textContent = data.failed;
  });
}
timer = setInterval(async () => {
  try { if ((await fetch("/state", {credentials: "same-origin"})).status === 401) ended(); }
  catch (error) { ended(); }
}, 10000);
"""

STYLE = """\
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { margin: 0; padding: 16px; }
main { max-width: 40rem; margin: 0 auto; }
button { font: inherit; padding: .5rem 1rem; }
.note { opacity: .7; font-size: .9rem; }
"""


def create_app(settings, sessions, port):
    lang = resolve(settings)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {"http://" + host for host in hosts}
    session_id = lambda request: request.cookies.get(COOKIE)

    def launch(request):
        sid = sessions.exchange(request.query_params.get("t"))
        if sid is None: return notice(lang, "ui.invalid", 403)
        audit.record(settings, "user", CLIENT, "ui.open")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(COOKIE, sid, httponly=True, samesite="strict", path="/")
        return response

    def index(request):
        if not sessions.check(session_id(request)): return notice(lang, "ui.expired", 401)
        return home(settings, lang)

    def state(request):
        if not sessions.check(session_id(request), touch=False): return JSONResponse({"active": False}, 401)
        return JSONResponse({"active": True, "paused": (settings.root / "paused").exists()})

    async def write(request):
        action = request.path_params["action"]
        if action not in WRITES: return JSONResponse({"error": "unknown action"}, 404)
        if request.headers.get("origin") not in origins: return JSONResponse({"error": "cross-origin"}, 403)
        sid = session_id(request)
        if not sessions.check(sid): return JSONResponse({"error": "session"}, 401)
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            return JSONResponse({"error": "JSON body required"}, 415)
        try: body = await request.json()
        except ValueError: body = None
        if not isinstance(body, dict): return JSONResponse({"error": "JSON object required"}, 400)
        prompt, run = WRITES[action]
        if "confirm" not in body:
            return JSONResponse({"confirm": sessions.confirm(sid, action), "message": t(prompt, lang)})
        if not sessions.redeem(sid, action, body["confirm"]): return JSONResponse({"error": "confirmation"}, 403)
        params = run(settings)
        audit.record(settings, "user", CLIENT, "ui." + action, params=params)
        return JSONResponse({"done": True, **params, "message": t("ui.done", lang)})

    routes = [
        Route("/launch", launch, methods=["GET"]),
        Route("/", index, methods=["GET"]),
        Route("/state", state, methods=["GET"]),
        Route("/ui.js", lambda request: Response(SCRIPT, media_type="text/javascript"), methods=["GET"]),
        Route("/ui.css", lambda request: Response(STYLE, media_type="text/css"), methods=["GET"]),
        Route("/api/{action}", write, methods=["POST"]),
    ]
    return Guard(Starlette(routes=routes), hosts)


def run(settings, open_browser=True, out=sys.stderr):
    import socket
    import uvicorn
    import webbrowser
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sessions = Sessions(on_end=lambda reason: audit.record(settings, "user", CLIENT, "ui.close", params={"reason": reason}))
    server = uvicorn.Server(uvicorn.Config(create_app(settings, sessions, port), log_level="warning", lifespan="off"))
    url = f"http://127.0.0.1:{port}/launch?t={sessions.launch_token()}"

    def watch():
        while not server.should_exit:
            time.sleep(2)
            if not sessions.sweep(): server.should_exit = True
    threading.Thread(target=watch, daemon=True).start()
    print(t("ui.open", resolve(settings), url=url), file=out, flush=True)
    if open_browser: webbrowser.open(url)
    server.run(sockets=[sock])
