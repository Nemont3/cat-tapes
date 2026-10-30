#!/usr/bin/env python3
"""cat-tape — one prompt in, one lofi VHS cat tape out.

  LTX-2.5 clip (video + its own sound) → ACE-Step 1.5 lofi track → mix (music on top, LTX ducked) → VHS grade → MP4

Stdlib only, so the CLI (`make_tape.sh`) and the app (`app/server.py`, on comfy-sdk) share it; the only difference
is the runner that talks to ComfyUI. Fails loud: any ComfyUI error, timeout, missing output or silent audio raises
TapeError and the CLI exits non-zero with the reason — never a silent default or an empty file.

Usage:
  tape.py make  [--prompt TEXT] [--preset ID] [--photo IMG] [--seed N] [--out DIR] [--server URL] [--stamp TEXT] [--aspect A]
  tape.py post  <ltx.mp4> <music.flac> <out.mp4> [--label TEXT] [--stamp TEXT]   # the ffmpeg half only (no GPU)
  tape.py presets
"""
import argparse, datetime, json, os, pathlib, random, re, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request, uuid

HERE = pathlib.Path(__file__).resolve().parent
WF_VIDEO = HERE / "workflows" / "ltx25_t2v.json"
WF_I2V = HERE / "workflows" / "ltx25_i2v.json"
WF_MUSIC = HERE / "workflows" / "ace15_music.json"
PRESETS = HERE / "presets.json"
FONT = os.environ.get("VHS_FONT", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf")

# Free text is wrapped so a one-line idea still reads like the long, structured prompts LTX-2.5 does best with.
STYLE = ("{p} Handheld camcorder footage, the operator following the cat at a slow walk, slight natural shake, "
         "imperfect framing, slightly late reframes. Warm natural light, cozy and calm. "
         "Soft ambient room sound.")
NEGATIVE = ("pc game, console game, video game, cartoon, childish, ugly, text, watermark, people, extra legs, extra limbs, "
            "extra paws, deformed, twisted body, merged animals, gimbal, steadicam, dolly shot, smooth camera glide")
# A sparse, drum-free lofi brief that ACE-Step 1.5 follows well; presets add a flavour.
MUSIC_TAGS = ("sparse minimal ambient instrumental, {bpm} BPM, {key}, {flavour}simple slow repeating melody of a few "
              "notes in the low and middle register only, no high notes, no bells, no chimes, no sparkling arpeggios, "
              "lots of space and silence between notes, no percussion at all, no drums, no snare, no hi-hat, no "
              "cymbals, no strings, no bass, gentle and nostalgic like a quiet video game soundtrack, muffled lo-fi, "
              "mono")
MUSIC_FLAVOUR = "solo soft felt piano and one warm analog synth pad only, "
TAPE_SECONDS = 10         # long enough for the melody to say something; LTX makes 10*24+1 = 241 frames
MUSIC_SECONDS = 16        # ACE needs some room to start a phrase; the tape uses the first clip-length of it
MUSIC_SEED_POOL = [777, 4242, 101]   # vetted seeds; free-text tapes draw from these, never a random one
LTX_DUCK_DB = -6          # LTX's own sound (purrs, rain, room tone) sits this far under the music
MAX_PROMPT = 600
# Kept on every tape: LTX-2.x licence Attachment A (5) asks that machine-generated content be disclosed as such, and §6
# that provenance metadata on Outputs is not removed — so ComfyUI's own tags are carried over too (-map_metadata 0).
AI_NOTICE = "AI-generated video: LTX-2.5 (picture and sound) and ACE-Step 1.5 (music), made with cat-tape"
PHOTO_DEFAULT = "The cat looks around curiously, blinks slowly at the camera, then settles down comfortably."
IMAGE_STRENGTH = 0.7      # first-pass hold on the photo (ComfyUI's LTX-2.5 i2v template); the refine pass uses 1.0
PHOTO_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")   # jpeg, png, webp (checked with WEBP below)


class TapeError(Exception):
    """A tape could not be made. The message is the reason, written for the person who pressed the button."""


# ---------------------------------------------------------------- ComfyUI runners
def substitute(obj, subs):
    """Fill "{{KEY}}" placeholders (same convention as lib/comfy_run.py); a missing key is an error."""
    if isinstance(obj, dict): return {k: substitute(v, subs) for k, v in obj.items()}
    if isinstance(obj, list): return [substitute(v, subs) for v in obj]
    if isinstance(obj, str):
        if obj.startswith("{{") and obj.endswith("}}") and obj.count("{{") == 1:
            key = obj[2:-2]
            if key not in subs: raise TapeError(f"workflow placeholder {{{{{key}}}}} has no value")
            return subs[key]
        for k in re.findall(r"\{\{(\w+)\}\}", obj):
            if k not in subs: raise TapeError(f"workflow placeholder {{{{{k}}}}} has no value")
            obj = obj.replace("{{" + k + "}}", str(subs[k]))
    return obj


def load_graph(path, subs):
    try: graph = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as e: raise TapeError(f"cannot read workflow {path}: {e}")
    return substitute(graph, subs)


class DirectComfy:
    """Talks to ComfyUI's own HTTP API (stdlib). Used by make_tape.sh; adapted from lib/comfy_run.py."""

    def __init__(self, server="http://127.0.0.1:8188", timeout=900):
        self.server = server.rstrip("/"); self.timeout = timeout

    def _http(self, path, data=None, raw=False, timeout=60):
        req = urllib.request.Request(self.server + path, data=data,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            raise TapeError(f"ComfyUI refused {path} (HTTP {e.code}): {_comfy_error(e.read())}")
        except (urllib.error.URLError, OSError) as e:
            raise TapeError(f"ComfyUI unreachable at {self.server}: {getattr(e, 'reason', e)}")
        return body if raw else json.loads(body.decode())

    def upload(self, path):
        """Put an app-prepared image in ComfyUI's input/ (the one place this studio may write in its tree). -> its name."""
        p = pathlib.Path(path); boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{p.name}\"\r\n"
                f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + \
               f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(self.server + "/upload/image", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: d = json.loads(r.read())
        except urllib.error.HTTPError as e: raise TapeError(f"ComfyUI refused the photo upload (HTTP {e.code}): {_comfy_error(e.read())}")
        except (urllib.error.URLError, OSError) as e: raise TapeError(f"ComfyUI unreachable at {self.server}: {getattr(e, 'reason', e)}")
        return d["name"] if not d.get("subfolder") else f"{d['subfolder']}/{d['name']}"

    def run(self, graph, out_dir, on_progress=None):
        """Submit, wait, download every output file into out_dir. -> (list of paths, exec seconds)."""
        r = self._http("/prompt", json.dumps({"prompt": graph, "client_id": uuid.uuid4().hex}).encode())
        if "error" in r: raise TapeError(f"ComfyUI rejected the workflow: {_comfy_error(r)}")
        pid = r["prompt_id"]; t0 = time.time()
        while True:
            h = self._http(f"/history/{pid}")
            if pid in h:
                st = h[pid].get("status", {})
                if st.get("status_str") == "error":
                    errs = [m[1] for m in st.get("messages", []) if isinstance(m, list) and m and m[0] == "execution_error"]
                    e = errs[0] if errs else {}
                    raise TapeError(f"ComfyUI failed in {e.get('node_type', '?')}: {str(e.get('exception_message', 'error'))[:300]}")
                if st.get("completed") or h[pid].get("outputs"): break
            if time.time() - t0 > self.timeout: raise TapeError(f"ComfyUI timed out after {self.timeout} s (job {pid})")
            if on_progress: on_progress(time.time() - t0)
            time.sleep(2)
        outs = []
        for o in h[pid]["outputs"].values():
            for val in o.values():
                if not isinstance(val, list): continue
                for f in [x for x in val if isinstance(x, dict) and "filename" in x]:
                    q = urllib.parse.urlencode({"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
                    dst = pathlib.Path(out_dir) / pathlib.Path(f["filename"]).name
                    dst.write_bytes(self._http("/view?" + q, raw=True, timeout=120)); outs.append(dst)
        ts = {m[0]: m[1].get("timestamp") for m in h[pid].get("status", {}).get("messages", [])
              if isinstance(m, list) and len(m) > 1 and isinstance(m[1], dict)}
        exe = (ts["execution_success"] - ts["execution_start"]) / 1000 if ts.get("execution_start") and ts.get("execution_success") else None
        return outs, exe


def _comfy_error(body):
    try: d = json.loads(body) if isinstance(body, (bytes, str)) else body
    except ValueError: return (body[:300].decode(errors="replace") if isinstance(body, bytes) else str(body)[:300])
    err = d.get("error", d)
    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
    nodes = [f"{n}: {', '.join(x.get('message', '') for x in v.get('errors', []))}" for n, v in d.get("node_errors", {}).items()]
    return (msg + (" — " + "; ".join(nodes) if nodes else ""))[:500]


def free_vram(server="http://127.0.0.1:8188"):
    """End-of-tape VRAM release : only when ComfyUI's queue is empty.
    -> a one-line status. Never raises: a tape that rendered is not failed by the clean-up."""
    try:
        q = json.load(urllib.request.urlopen(server + "/queue", timeout=10))
        if q.get("queue_running") or q.get("queue_pending"): return "VRAM kept: other ComfyUI jobs are queued"
        req = urllib.request.Request(server + "/free", data=json.dumps({"unload_models": True, "free_memory": True}).encode(),
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return "VRAM released"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return f"VRAM NOT released ({e}) — run lib/comfy_free.py"


class VramPeak:
    """Samples whole-card memory once a second while a tape renders (same method as the 09-28 benchmark)."""

    def __init__(self): self.peak = None; self._stop = threading.Event(); self._t = threading.Thread(target=self._loop, daemon=True)
    def __enter__(self): self._t.start(); return self
    def __exit__(self, *a): self._stop.set(); self._t.join(timeout=3)

    def _loop(self):
        while not self._stop.is_set():
            try:
                mib = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                         capture_output=True, text=True, timeout=5).stdout.split()[0])
                self.peak = max(self.peak or 0, mib)
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass  # measurement only; `peak` stays None and the sidecar says so
            self._stop.wait(1)


# ---------------------------------------------------------------- ffmpeg half
def _ff(args, what):
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", *args], capture_output=True, text=True)
    if p.returncode:   # the FIRST lines carry the cause; the tail is the downstream fallout
        raise TapeError(f"ffmpeg failed while {what}: {' | '.join(p.stderr.strip().splitlines()[:2])[:400]}")


def probe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    if p.returncode: raise TapeError(f"cannot read {pathlib.Path(path).name}: {p.stderr.strip()[-300:]}")
    d = json.loads(p.stdout)
    return {"duration": float(d.get("format", {}).get("duration", 0) or 0), "streams": d.get("streams", [])}


def prepare_photo(src, dst):
    """The photo we send is a copy we made: a real jpeg/png/webp, centre-cropped to 4:3, 1536×1152, metadata stripped
    (no location or camera tags leave with it), under an app-generated name."""
    try: head = pathlib.Path(src).read_bytes()[:16]
    except OSError as e: raise TapeError(f"cannot read the photo: {e}")
    if not (head.startswith(PHOTO_MAGIC[:2]) or (head.startswith(PHOTO_MAGIC[2]) and head[8:12] == b"WEBP")):
        raise TapeError("the photo must be a JPEG, PNG or WebP image")
    _ff(["-i", str(src), "-frames:v", "1", "-map_metadata", "-1",
         "-vf", "scale=1536:1152:force_original_aspect_ratio=increase:flags=lanczos,crop=1536:1152", str(dst)], "preparing the photo")
    return pathlib.Path(dst)


def mean_volume(path):
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+|-inf) dB", p.stderr)
    return float(m.group(1)) if m and m.group(1) != "-inf" else float("-inf")


# A camcorder paused and restarted (the Evening Tape's cuts): half a second of tape noise, colour tear, rolling bands and
# a white flash, then a blinking red REC. Every part is limited to the cut with the filter's own `enable`.
GLITCH = ("noise=alls=80:allf=t+u:enable='lt(t,0.45)',rgbashift=rh=-12:bh=12:enable='lt(t,0.3)',hue=s=0.3:enable='lt(t,0.2)',"
          "eq=brightness=0.18:enable='lt(t,0.08)',"
          + "".join(f"drawbox=x=0:y='mod(t*2400+{o}\\,480)':w=iw:h=18:color=white@0.35:t=fill:enable='lt(t,0.45)',"
                    for o in (0, 170, 330))
          + f"drawtext=fontfile={FONT}:text='● REC':x=w-tw-28:y=24:fontsize=24:fontcolor=red@0.9:shadowcolor=black@0.6:"
            "shadowx=1:shadowy=1:enable='lt(t\\,1.6)*lt(mod(t\\,0.5)\\,0.3)',")


def handheld(seed=0):
    """A heavy camcorder in someone's hands : slow
    drift, a little faster shake and a small roll, from sums of sines with seeded phases. Crops 8 % so the moving
    window never shows an edge. Applied before the 4:3 crop; VHS_SHAKE scales it (0 = locked off)."""
    r = random.Random(seed); ph = [round(r.uniform(0, 6.283), 3) for _ in range(9)]
    amp = float(os.environ.get("VHS_SHAKE", "1.0"))
    wob = lambda a, b, c: f"(0.55*sin(2*PI*0.21*t+{a})+0.30*sin(2*PI*0.67*t+{b})+0.15*sin(2*PI*2.3*t+{c}))"
    return (f"rotate=a='{0.006 * amp:.4f}*{wob(*ph[0:3])}':fillcolor=black,"
            f"crop=w=iw*0.92:h=ih*0.92:x='(iw-ow)/2*(1+{0.75 * amp:.3f}*{wob(*ph[3:6])})':"
            f"y='(ih-oh)/2*(1+{0.75 * amp:.3f}*{wob(*ph[6:9])})',")


def vhs_filter(label=None, stamp=None, seed=0, glitch=False):
    """lib/vhs.sh's grade (640×480 4:3 picture, chroma bleed, noise, date stamp, PLAY ▶, scanlines on a 1440×1080
    file: the 640×480 look, delivered sharp), made ALIVE: grain that changes every frame and swells in strength, a slight luma flicker, chroma that crawls
    about a pixel, and now and then a faint tracking line. Plus the handheld drift and an optional cassette label."""
    stamp = stamp or datetime.datetime.now().strftime("%b %-d %Y  %-I:%M %p").upper()
    esc = lambda s: s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")
    blur = os.environ.get("VHS_BLUR", "1.2"); noise = os.environ.get("VHS_NOISE", "14"); ch = int(os.environ.get("VHS_CHROMA", "3"))
    sat = os.environ.get("VHS_SAT", "1.15"); con = os.environ.get("VHS_CONTRAST", "1.05")
    txt = f"fontfile={FONT}:fontsize=22:fontcolor=white@0.85:shadowcolor=black@0.6:shadowx=1:shadowy=1"
    crawl = f"({ch}+1.4*sin(2*PI*1.7*t)*sin(2*PI*0.31*t))"     # the colour offset wanders by about a pixel
    swell = "0.35*(0.5+0.5*sin(2*PI*0.43*T))"                  # share of the coarse grain, breathing in and out
    v = (handheld(seed) +
         "crop='min(iw,ih*4/3)':'min(ih,iw*3/4)',scale=640:480:flags=bicubic,"   # 4:3 from either side
         "split=3[a][b][c];[a]lutrgb=g=0:b=0[r];[b]lutrgb=r=0:b=0[g];[c]lutrgb=r=0:g=0[bl];"
         f"[r]pad=iw+16:ih:8:0,crop=640:480:x='8-{crawl}':y=0[r2];[bl]pad=iw+16:ih:8:0,crop=640:480:x='8+{crawl}':y=0[b2];"
         "[g][r2]blend=all_mode=addition[rg];[rg][b2]blend=all_mode=addition,"
         f"gblur=sigma={blur},split[fine][coarse];"
         f"[fine]noise=alls={noise}:allf=t+u[fg];[coarse]scale=320:240,noise=alls=24:allf=t+u,scale=640:480:flags=bilinear[cg];"
         f"[fg][cg]blend=all_expr='A*(1-{swell})+B*{swell}',"
         f"eq=saturation={sat}:contrast={con}:brightness='0.02+0.012*sin(2*PI*7.1*t)*sin(2*PI*0.9*t)':eval=frame,"
         # a faint tracking line rolls down the frame for a moment every few seconds
         "drawbox=x=0:y='mod(t*170\\,520)-20':w=iw:h=3:color=white@0.10:t=fill:enable='lt(mod(t\\,2.9)\\,0.35)',"
         "drawbox=x=0:y='mod(t*170\\,520)-14':w=iw:h=1:color=black@0.18:t=fill:enable='lt(mod(t\\,2.9)\\,0.35)',"
         + (GLITCH if glitch else "") +
         f"drawtext={txt}:text='{esc(stamp)}':x=w-tw-28:y=h-th-24,"
         f"drawtext={txt}:text='PLAY  ▶':x=28:y=24,")
    if label:
        v += (f"drawtext=fontfile={FONT}:fontsize=30:fontcolor=white@0.9:box=1:boxcolor=black@0.45:boxborderw=10:"
              f"text='{esc(label)}':x=(w-tw)/2:y=h*0.42:enable='lt(t,1.5)',")
    v += "vignette=PI/5,scale=1440:1080:flags=neighbor,drawgrid=w=iw:h=2:t=1:c=black@0.12,format=yuv420p"
    return v


def post(ltx_clip, music, out, label=None, stamp=None, seed=0):
    """Mix + grade + mux. The music gets lib/camcorder_audio.sh's finish (dark, near-mono, −18 LUFS), trimmed to the
    clip with short fades; LTX's own sound sits LTX_DUCK_DB underneath."""
    info = probe(ltx_clip)
    if not any(s["codec_type"] == "video" for s in info["streams"]): raise TapeError("the LTX clip has no video stream")
    if not any(s["codec_type"] == "audio" for s in info["streams"]): raise TapeError("the LTX clip has no audio stream (its own sound is part of the mix)")
    d = info["duration"]
    if d < 1: raise TapeError(f"the LTX clip is {d:.2f} s long")
    if probe(music)["duration"] < d: raise TapeError(f"the music track is shorter than the clip ({d:.2f} s)")
    if mean_volume(music) < -60: raise TapeError("the music track is silent")
    fade = 2.5 if d > 7 else 1.5
    fo = max(0.0, d - fade)
    af = ("[1:a]aresample=48000,highpass=f=70,lowpass=f=4500,lowpass=f=4500,"
          "pan=stereo|c0=0.65*c0+0.35*c1|c1=0.35*c0+0.65*c1,"
          "acompressor=threshold=-22dB:ratio=2.5:attack=20:release=300,loudnorm=I=-18:LRA=5:TP=-2,"
          f"aresample=48000,atrim=0:{d:.3f},afade=t=in:d=0.4,afade=t=out:st={fo:.3f}:d={fade}[m];"
          f"[0:a]aresample=48000,aformat=channel_layouts=stereo,volume={LTX_DUCK_DB}dB,atrim=0:{d:.3f}[l];"
          "[m][l]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.89[a]")
    out = pathlib.Path(out); tmp = out.with_suffix(".part.mp4")
    _ff(["-i", str(ltx_clip), "-i", str(music), "-filter_complex", f"[0:v]{vhs_filter(label, stamp, seed)}[v];{af}",
         "-map", "[v]", "-map", "[a]", "-map_metadata", "0", "-metadata", f"comment={AI_NOTICE}",
         "-t", f"{d:.3f}", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart+use_metadata_tags", str(tmp)], "grading and mixing the tape")
    verify(tmp, d)
    tmp.replace(out)
    return out


def verify(path, want_duration):
    """The tape must be what we say it is: 1440×1080 video, an audible audio stream, the clip's length."""
    info = probe(path)
    v = [s for s in info["streams"] if s["codec_type"] == "video"]; a = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not v or (v[0].get("width"), v[0].get("height")) != (1440, 1080): raise TapeError(f"tape video is not 1440×1080: {v}")
    if not a: raise TapeError("tape has no audio stream")
    if abs(info["duration"] - want_duration) > 0.25: raise TapeError(f"tape is {info['duration']:.2f} s, the clip was {want_duration:.2f} s")
    if mean_volume(path) < -50: raise TapeError("tape audio is silent")
    tags = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                                     capture_output=True, text=True).stdout or "{}").get("format", {}).get("tags", {})
    if "AI-generated" not in tags.get("comment", ""): raise TapeError("tape lost its AI-generated notice")
    return info


# ---------------------------------------------------------------- the whole tape
def load_presets():
    try: return json.loads(PRESETS.read_text())
    except (OSError, ValueError) as e: raise TapeError(f"cannot read presets.json: {e}")


def plan_tape(prompt=None, preset=None, seed=None, aspect="4:3 (Standard)", photo=None):
    """-> the full recipe for one tape (everything a render needs, nothing rendered yet)."""
    if preset:
        presets = load_presets()
        if preset not in presets: raise TapeError(f"no preset {preset!r} (have: {', '.join(presets)})")
        p = presets[preset]
    else:
        p = {}
    text = (prompt or "").strip()
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    if len(text) > MAX_PROMPT: raise TapeError(f"prompt is {len(text)} characters; the limit is {MAX_PROMPT}")
    if not text and not p and not photo: raise TapeError("give a prompt, a preset or a photo")
    if photo:   # a photo of a real cat: the preset's scene would fight it, so only its music and label carry over
        video_prompt = STYLE.format(p=(text or PHOTO_DEFAULT).rstrip(".") + ".")
    else:
        video_prompt = p["prompt"] if p and not text else STYLE.format(p=text.rstrip(".") + ".")
    m = p.get("music", {})
    rnd = random.Random()
    return {
        "preset": preset, "label": p.get("label") or ("YOUR CAT" if photo else None), "aspect": aspect, "seconds": TAPE_SECONDS,
        "photo": str(photo) if photo else None, "image_strength": IMAGE_STRENGTH,
        "video": {"prompt": video_prompt, "negative": NEGATIVE,
                  "seed": int(seed) if seed is not None else (p["seed"] if p and not text and not photo else rnd.randrange(2**31))},
        "music": {"tags": MUSIC_TAGS.format(bpm=m.get("bpm", 64), key=m.get("key", "D minor"),
                                            flavour=m.get("flavour", MUSIC_FLAVOUR)),
                  "bpm": m.get("bpm", 64), "key": m.get("key", "D minor"), "seconds": MUSIC_SECONDS,
                  "seed": m.get("seed", rnd.choice(MUSIC_SEED_POOL))},
    }


def make_tape(recipe, runner, out_dir, stamp=None, on_stage=None, free_server="http://127.0.0.1:8188"):
    """Render and assemble one tape. -> (path to the MP4, report dict). Raises TapeError."""
    say = on_stage or (lambda stage, **kw: None)
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tape_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{'photo' if recipe.get('photo') else recipe['preset'] or 'custom'}-{recipe['video']['seed']}"
    work = out_dir / "work" / tape_id; work.mkdir(parents=True)
    report = {"id": tape_id, "recipe": recipe, "stages": {}}
    t_all = time.time()
    try:
        with VramPeak() as vram:
            say("video", tape_id=tape_id)
            t = time.time()
            subs = {"NAME": tape_id, "PROMPT": recipe["video"]["prompt"], "NEGATIVE": recipe["video"]["negative"],
                    "SEED": recipe["video"]["seed"], "ASPECT": recipe["aspect"], "SECONDS": recipe.get("seconds", TAPE_SECONDS)}
            if recipe.get("photo"):
                photo = prepare_photo(recipe["photo"], work / f"{tape_id}.png")
                subs.update(IMAGE=runner.upload(photo), IMAGE_STRENGTH=recipe.get("image_strength", IMAGE_STRENGTH))
            g = load_graph(WF_I2V if recipe.get("photo") else WF_VIDEO, subs)
            outs, exe = runner.run(g, work, on_progress=lambda s: say("video", elapsed=s))
            clips = [o for o in outs if o.suffix == ".mp4"]
            if not clips: raise TapeError(f"LTX finished without a video file (got: {[o.name for o in outs] or 'nothing'})")
            report["stages"]["video"] = {"wall_s": round(time.time() - t, 1), "exec_s": exe, "file": clips[0].name}

            say("music")
            t = time.time()
            m = recipe["music"]
            g = load_graph(WF_MUSIC, {"NAME": tape_id, "TAGS": m["tags"], "LYRICS": "[Instrumental]", "BPM": m["bpm"],
                                      "KEY": m["key"], "SECONDS": m["seconds"], "SEED": m["seed"]})
            outs, exe = runner.run(g, work, on_progress=lambda s: say("music", elapsed=s))
            tracks = [o for o in outs if o.suffix in (".flac", ".mp3", ".wav", ".opus")]
            if not tracks: raise TapeError(f"ACE-Step finished without an audio file (got: {[o.name for o in outs] or 'nothing'})")
            report["stages"]["music"] = {"wall_s": round(time.time() - t, 1), "exec_s": exe, "file": tracks[0].name}
        report["peak_vram_mib"] = vram.peak
        say("tape")
        t = time.time()
        out = post(clips[0], tracks[0], out_dir / f"{tape_id}.mp4", label=recipe.get("label"), stamp=stamp, seed=recipe["video"]["seed"])
        report["stages"]["post"] = {"wall_s": round(time.time() - t, 1)}
    finally:
        report["vram"] = free_vram(free_server)
        report["total_s"] = round(time.time() - t_all, 1)
        (work / "report.json").write_text(json.dumps(report, indent=1))
    report["file"] = str(out); report["probe"] = probe(out)
    (out_dir / f"{tape_id}.json").write_text(json.dumps(report, indent=1))
    say("done", file=str(out))
    return out, report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make"); mk.add_argument("--prompt", default=""); mk.add_argument("--preset"); mk.add_argument("--seed", type=int)
    mk.add_argument("--out", default=str(HERE / "out")); mk.add_argument("--server", default="http://127.0.0.1:8188")
    mk.add_argument("--stamp"); mk.add_argument("--aspect", default="4:3 (Standard)"); mk.add_argument("--timeout", type=int, default=900)
    mk.add_argument("--dry-run", action="store_true", help="print the recipe; render nothing")
    mk.add_argument("--photo", help="image-to-video: a photo of a cat (a prepared copy is sent, never the original)")
    po = sub.add_parser("post"); po.add_argument("clip"); po.add_argument("music"); po.add_argument("out")
    po.add_argument("--label"); po.add_argument("--stamp"); po.add_argument("--seed", type=int, default=0, help="handheld drift phases")
    sub.add_parser("presets")
    a = ap.parse_args()
    try:
        if a.cmd == "presets":
            for k, v in load_presets().items(): print(f"{k:16} {v['label']}")
        elif a.cmd == "post":
            print(post(a.clip, a.music, a.out, a.label, a.stamp, a.seed))
        else:
            recipe = plan_tape(a.prompt, a.preset, a.seed, a.aspect, a.photo)
            if a.dry_run: print(json.dumps(recipe, indent=1)); return
            last = [None]
            def say(stage, **kw):
                if stage != last[0]: print(f"[{time.strftime('%H:%M:%S')}] {stage}", file=sys.stderr); last[0] = stage
            out, rep = make_tape(recipe, DirectComfy(a.server, a.timeout), a.out, a.stamp, say, free_server=a.server)
            print(json.dumps({"file": str(out), "total_s": rep["total_s"], "peak_vram_mib": rep["peak_vram_mib"],
                              "stages": rep["stages"], "vram": rep["vram"]}))
    except TapeError as e:
        print(f"cat-tape: FAILED — {e}", file=sys.stderr); sys.exit(2)


if __name__ == "__main__":
    main()
