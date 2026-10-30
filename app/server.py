#!/usr/bin/env python3
"""cat-tape app: a small local web page that makes lofi VHS cat tapes on comfy-sdk → comfy-api-proxy → ComfyUI.

Loopback only. Run it with the comfy venv's python (the only place comfy-sdk is installed):

  COMFY_BASE_URL=http://127.0.0.1:8189 COMFY_ROUTER_BASE_URL=http://127.0.0.1:9 \
  COMFY_API_PROXY_TOKEN=<proxy token> CAT_TAPE_OUT=<abs dir> .venv-comfy/bin/python -I app/server.py [--port 8190]

It refuses to start unless that environment holds: the SDK base URL and the
router on loopback, no COMFY_API_KEY, no *_PROXY variables. It never calls client.models.* and never accepts a
URL from the page; every file it writes is under CAT_TAPE_OUT with a name it generated.
"""
import argparse, base64, binascii, http.server, json, os, pathlib, re, sys, threading, time, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import tape  # noqa: E402  (the shared pipeline, stdlib only)
import evening  # noqa: E402  (AN EVENING TAPE: four scenes, one track)

LOOPBACK = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\]):\d+/?$")
TAPE_NAME = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]+-[0-9]+\.mp4$")
MAX_PHOTO = 10 * 1024 * 1024   # bytes, decoded


def check_env():
    """The loopback-only conditions, checked in code. -> (base_url, token, out_dir)."""
    problems = []
    base = os.environ.get("COMFY_BASE_URL", "")
    if not LOOPBACK.match(base): problems.append(f"COMFY_BASE_URL must be the loopback proxy (is {base!r})")
    if not LOOPBACK.match(os.environ.get("COMFY_ROUTER_BASE_URL", "")): problems.append("COMFY_ROUTER_BASE_URL must point at a dead loopback sink")
    if os.environ.get("COMFY_API_KEY"): problems.append("COMFY_API_KEY must be unset")
    proxies = [k for k in os.environ if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")]
    if proxies: problems.append(f"unset {', '.join(proxies)}")
    token = os.environ.get("COMFY_API_PROXY_TOKEN", "").strip()
    if not token: problems.append("COMFY_API_PROXY_TOKEN is missing (the proxy refuses requests without it)")
    out = os.environ.get("CAT_TAPE_OUT", "")
    if not out or not os.path.isabs(out): problems.append("CAT_TAPE_OUT must be an absolute directory")
    if problems: raise SystemExit("cat-tape app will not start:\n  - " + "\n  - ".join(problems))
    return base.rstrip("/"), token, pathlib.Path(out)


class SdkComfy:
    """The tape pipeline's runner, on comfy-sdk through the local comfy-api-proxy."""

    def __init__(self, token, timeout=900):
        from comfy_sdk import Comfy  # imported here so `tape.py` stays usable without the SDK
        self.client = Comfy(api_key=token, timeout=60.0, client_info="cat-tape")
        self.timeout = timeout

    def upload(self, path):
        """An app-prepared photo as an SDK asset handle (uploaded at submit). Never assets.from_url."""
        return self.client.assets.from_file(str(path))

    def run(self, graph, out_dir, on_progress=None):
        from comfy_sdk import ComfyError, Workflow
        t0 = time.time()
        try:
            job = self.client.submit(Workflow(graph))   # no metadata: proxy 0.1.6 wants a string, SDK 0.5.0 sends a map
            while True:
                job.refresh()
                if job.status in ("succeeded", "failed", "canceled", "expired"): break
                if time.time() - t0 > self.timeout: raise tape.TapeError(f"ComfyUI timed out after {self.timeout} s (job {job.id})")
                if on_progress: on_progress(time.time() - t0)
                time.sleep(2)
            if job.status != "succeeded": raise tape.TapeError(f"ComfyUI job {job.status}: {str(job.error)[:300]}")
            outs = []
            for o in job.outputs:
                dst = pathlib.Path(out_dir) / pathlib.Path(o.name).name   # basename only: never a path from the server
                o.to_file(dst); outs.append(dst)
            return outs, None
        except tape.TapeError:
            raise
        except ComfyError as e:
            raise tape.TapeError(f"ComfyUI said: {e}")
        except Exception as e:  # httpx connect/read errors and anything else: say what it was, never continue
            raise tape.TapeError(f"could not reach ComfyUI through the proxy ({type(e).__name__}: {e})")


class Studio:
    """One tape at a time (the card holds one LTX render); the page polls the status."""

    def __init__(self, runner, out_dir):
        self.runner = runner; self.out = out_dir; self.lock = threading.Lock(); self.jobs = {}; self.busy = None

    def start(self, prompt, preset, photo_bytes=None, cast=None):
        with self.lock:
            if self.busy: raise tape.TapeError("a tape is already recording; one at a time")
            jid = f"j{int(time.time() * 1000)}"
            photo = None
            if photo_bytes:   # saved under a name we made, in our own dir; tape.prepare_photo checks it is an image
                up = self.out / "uploads"; up.mkdir(parents=True, exist_ok=True)
                photo = up / f"{jid}.img"; photo.write_bytes(photo_bytes)
            # validates input before anything is queued; a cast means AN EVENING TAPE
            recipe = evening.plan_evening(cast, "describe") if cast else tape.plan_tape(prompt, preset, photo=photo)
            self.busy = jid
            self.jobs[jid] = {"stage": "queued", "started": time.time(), "label": recipe["label"]}
        threading.Thread(target=self._run, args=(jid, recipe), daemon=True).start()
        return jid

    def _run(self, jid, recipe):
        st = self.jobs[jid]
        def say(stage, **kw):
            st["stage"] = stage
            if "file" in kw: st["file"] = pathlib.Path(kw["file"]).name
        try:
            free = os.environ.get("COMFYUI_FREE_URL", "http://127.0.0.1:8188")
            if "cast" in recipe: evening.make_evening(recipe, self.runner, self.out, on_stage=say, free_server=free)
            else: tape.make_tape(recipe, self.runner, self.out, on_stage=say, free_server=free)
        except tape.TapeError as e:
            st["stage"] = "failed"; st["error"] = str(e)
        except Exception as e:
            st["stage"] = "failed"; st["error"] = f"unexpected {type(e).__name__}: {e}"
        finally:
            st["ended"] = time.time()
            with self.lock: self.busy = None

    def status(self, jid):
        st = dict(self.jobs.get(jid) or {})
        if st: st["elapsed"] = round((st.get("ended") or time.time()) - st["started"])
        return st


def handler(studio):
    index = (HERE / "static" / "index.html").read_bytes()

    class H(http.server.BaseHTTPRequestHandler):
        server_version = "cat-tape"

        def log_message(self, fmt, *a): sys.stderr.write("cat-tape %s\n" % (fmt % a))

        def _send(self, code, body, ctype="application/json"):
            if isinstance(body, (dict, list)): body = json.dumps(body).encode()
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers(); self.wfile.write(body)

        def _host_ok(self):  # loopback Host only: a DNS-rebinding page cannot drive the studio
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def do_GET(self):
            if not self._host_ok(): return self._send(403, {"error": "loopback only"})
            path = urllib.parse.urlsplit(self.path).path
            if path == "/": return self._send(200, index, "text/html; charset=utf-8")
            m = re.fullmatch(r"/static/(den-scene\.webp|den-wall\.webp|osd\.ttf)", path)   # the page's own assets only
            if m:
                ctype = "font/ttf" if m.group(1).endswith(".ttf") else "image/webp"
                return self._send(200, (HERE / "static" / m.group(1)).read_bytes(), ctype)
            if path == "/api/cast":
                return self._send(200, [{"id": k, "name": v["name"]} for k, v in evening.CAST.items()])
            if path == "/api/presets":
                return self._send(200, [{"id": k, "label": v["label"]} for k, v in tape.load_presets().items()])
            m = re.fullmatch(r"/api/tapes/(j[0-9]+)", path)
            if m:
                st = studio.status(m.group(1))
                return self._send(200 if st else 404, st or {"error": "no such tape"})
            m = re.fullmatch(r"/tapes/([^/]+)", path)
            if m and TAPE_NAME.match(m.group(1)) and (studio.out / m.group(1)).is_file():
                data = (studio.out / m.group(1)).read_bytes()
                self.send_response(200); self.send_header("Content-Type", "video/mp4"); self.send_header("Content-Length", str(len(data)))
                if "download" in urllib.parse.urlsplit(self.path).query:
                    self.send_header("Content-Disposition", f'attachment; filename="{m.group(1)}"')
                self.end_headers(); self.wfile.write(data); return
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok(): return self._send(403, {"error": "loopback only"})
            if urllib.parse.urlsplit(self.path).path != "/api/tapes": return self._send(404, {"error": "not found"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_PHOTO * 4 // 3 + 8192: return self._send(413, {"error": "that photo is too big (10 MB at most)"})
                req = json.loads(self.rfile.read(n) or b"{}")
                preset = req.get("preset") or None; prompt = req.get("prompt") or ""; photo = req.get("photo"); cast = req.get("cast") or None
                if any(v is not None and not isinstance(v, str) for v in (preset, photo, cast)) or not isinstance(prompt, str):
                    return self._send(400, {"error": "preset, prompt, cast and photo must be text"})
                if photo:   # image-to-video is not part of the app; tape.py --photo keeps it
                    return self._send(400, {"error": "photo tapes are not part of this version"})
                photo_bytes = None
                if photo_bytes and len(photo_bytes) > MAX_PHOTO: return self._send(413, {"error": "that photo is too big (10 MB at most)"})
                return self._send(202, {"id": studio.start(prompt, preset, photo_bytes, cast)})
            except tape.TapeError as e:
                return self._send(409 if "already recording" in str(e) else 400, {"error": str(e)})
            except (ValueError, binascii.Error):
                return self._send(400, {"error": "send JSON (a photo as base64)"})
    return H


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8190); a = ap.parse_args()
    _, token, out = check_env()
    out.mkdir(parents=True, exist_ok=True)
    evening.CACHE = out / "cache"   # keep every write under CAT_TAPE_OUT (the app may run with the project read-only)
    studio = Studio(SdkComfy(token), out)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler(studio))   # loopback, never 0.0.0.0
    print(f"cat-tape: http://127.0.0.1:{a.port}/  (tapes → {out})", file=sys.stderr)
    srv.serve_forever()


if __name__ == "__main__":
    main()
