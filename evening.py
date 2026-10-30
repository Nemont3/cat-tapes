#!/usr/bin/env python3
"""evening.py — AN EVENING TAPE: one cat's evening, four 10 s scenes cut together like a camcorder paused and
restarted, the date stamp advancing, ONE continuous lofi track under all of it.

  evening.py make --cast pink-collar [--method describe|chain] [--seed N] [--out DIR] [--server URL] [--dry-run]

Methods for keeping the SAME cat across scenes (we tested both; describe won):
  describe  every scene repeats the cast's fixed, detailed description (text-to-video each time)
  chain     scene 1 is text-to-video; each later scene starts from the LAST frame of the scene before it
            (image-to-video on our own generated frame, never a user photo)
"""
import argparse, datetime, hashlib, json, pathlib, shutil, sys, time
import tape
from tape import TapeError

# Chosen for consistency across scenes and for being easy to tell apart.
CAST = {
    "pink-collar": {"name": "the little black cat",
                    "look": ("a small sleek black cat with short glossy black fur, big round golden-yellow eyes, a slim body "
                             "and a bright hot-pink collar with a tiny silver bell")},
    "orange-fluff": {"name": "the fluffy orange cat",
                     "look": ("a big fluffy long-haired orange tabby cat with a cream-white chest ruff, bright green eyes, "
                              "white whiskers and a thick bushy striped tail")},
    "white-socks": {"name": "the black cat with white socks",
                    "look": ("a realistic ordinary black-and-white tuxedo house cat with short natural fur, normal adult "
                             "cat proportions, a white chest, four white paws like little socks, green eyes and a black "
                             "tail, photographed like a real pet")},
}
CAM = ("Handheld camcorder footage filmed from a few steps away, slight natural shake, imperfect framing, slightly late "
       "reframes. The cat is busy with what it is doing and does not look at the camera.")
# One afternoon-into-evening OUTSIDE, a cat's little adventure, ending AT the sunset glow . Light words
# only (no dusk, night or dim), so no scene comes out darker than the sunset.
SCENES = [
    {"title": "TALL GRASS", "time": "4:48 PM",
     "action": ("creeps low through tall sunlit meadow grass in a backyard, stalking something, then pounces"),
     "sound": "Grass rustling, crickets and birdsong.", "light": "Bright warm late-afternoon daylight, sunlit green grass."},
    {"title": "DANDELIONS", "time": "5:21 PM",
     "action": ("sits up among white dandelion puffs in a sunny garden and bats at them with its front paws, seeds "
                "floating up around it"),
     "sound": "A soft breeze and distant birdsong.", "light": "Warm natural daylight turning golden, soft glowing seeds."},
    {"title": "FENCE TOP", "time": "6:02 PM",
     "action": ("is standing firmly on the top rail of a wooden garden fence, paws gripping the rail and its weight on "
                "it, watching small birds in a nearby tree, its tail swishing, chattering softly at them"),
     "negative": "floating, levitating, hovering in the air",
     "sound": "Birds chirping and a gentle breeze.",
     "light": ("Bright sunny golden hour, the cat and the fence lit directly by warm low sunlight from in front, an open "
               "bright sky behind the tree, a well-exposed sunlit image.")},
    {"title": "SUNSET", "time": "6:31 PM",
     "action": ("sits on a grassy hill facing a big pink-orange sunset sky, its outline glowing, ears turning, then it "
                "looks back over its shoulder"),
     "sound": "A soft evening breeze and faraway birds.", "light": "Bright pink-orange sunset glow filling the sky, warm rim light on the cat."},
]
MUSIC_SECONDS = 48          # one track under the whole evening: room for the melody to develop
CHAIN_STRENGTH = 0.6        # how hard a chained scene holds the previous scene's last frame (template default 0.7)
CUT_CLICK = "anoisesrc=d=0.12:c=pink:a=0.18"   # the click of a camcorder restarting, at each cut


def scene_prompt(cast, scene):
    c = CAST[cast]
    return (f"{c['look'][0].upper()}{c['look'][1:]} {scene['action']}. {CAM} {scene['sound']} {scene['light']} "
            f"Throughout the shot it is {c['look']}.")


def plan_evening(cast, method="describe", seed=None, reseed=None):
    if cast not in CAST: raise TapeError(f"no cast {cast!r} (have: {', '.join(CAST)})")
    if method not in ("describe", "chain"): raise TapeError(f"no method {method!r} (describe | chain)")
    import random
    seed = int(seed) if seed is not None else random.randrange(2**31)
    return {"cast": cast, "method": method, "seed": seed, "label": "AN EVENING",
            "scenes": [{"title": s["title"], "time": s["time"], "prompt": scene_prompt(cast, s),
                        "negative": tape.NEGATIVE + (", " + s["negative"] if s.get("negative") else ""),
                        "seed": (reseed or {}).get(i + 1, seed + i)} for i, s in enumerate(SCENES)],
            "music": {"tags": tape.MUSIC_TAGS.format(bpm=62, key="D minor", flavour=tape.MUSIC_FLAVOUR), "bpm": 62,
                      "key": "D minor", "seconds": MUSIC_SECONDS, "seed": 777}}


CACHE = tape.HERE / "out" / "evening" / "cache"


def cache_key(wf, subs, method, prev):
    """Everything that decides a scene's pixels: the graph file, its inputs (minus the per-run name) and, when chained,
    the clip it starts from."""
    h = hashlib.sha256(pathlib.Path(wf).read_bytes())
    h.update(json.dumps({k: v for k, v in subs.items() if k not in ("NAME", "IMAGE")}, sort_keys=True).encode())
    h.update(method.encode())
    if prev: h.update(pathlib.Path(prev).read_bytes())
    return h.hexdigest()[:20]


def last_frame(clip, dst):
    tape._ff(["-sseof", "-0.1", "-i", str(clip), "-frames:v", "1", "-update", "1", str(dst)], "taking the last frame")
    return dst


def make_evening(recipe, runner, out_dir, on_stage=None, free_server="http://127.0.0.1:8188"):
    say = on_stage or (lambda stage, **kw: None)
    out_dir = pathlib.Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tid = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + f"-evening-{recipe['cast']}-{recipe['method']}-{recipe['seed']}"
    work = out_dir / "work" / tid; work.mkdir(parents=True)
    report = {"id": tid, "recipe": recipe, "stages": {}}
    t_all = time.time(); clips = []
    try:
        with tape.VramPeak() as vram:
            for i, sc in enumerate(recipe["scenes"]):
                say(f"scene {i + 1}/{len(recipe['scenes'])}: {sc['title']}")
                t = time.time()
                subs = {"NAME": f"{tid}-s{i + 1}", "PROMPT": sc["prompt"], "NEGATIVE": sc.get("negative", tape.NEGATIVE), "SEED": sc["seed"],
                        "ASPECT": "4:3 (Standard)", "SECONDS": tape.TAPE_SECONDS}
                wf = tape.WF_VIDEO
                if recipe["method"] == "chain" and clips:
                    frame = tape.prepare_photo(last_frame(clips[-1], work / f"s{i}-last.png"), work / f"s{i + 1}-start.png")
                    subs.update(IMAGE=runner.upload(frame), IMAGE_STRENGTH=CHAIN_STRENGTH); wf = tape.WF_I2V
                key = cache_key(wf, subs, recipe["method"], clips[-1] if clips and recipe["method"] == "chain" else None)
                hit = CACHE / f"{key}.mp4"
                if hit.exists():   # the same graph, prompt and seed rendered before: reuse it (iterating on one scene)
                    dst = work / f"s{i + 1}-cached.mp4"; shutil.copy(hit, dst); clips.append(dst)
                    report["stages"][f"scene{i + 1}"] = {"cached": key}; continue
                outs, exe = runner.run(tape.load_graph(wf, subs), work)
                mp4 = [o for o in outs if o.suffix == ".mp4"]
                if not mp4: raise TapeError(f"scene {i + 1} finished without a video file")
                CACHE.mkdir(parents=True, exist_ok=True); shutil.copy(mp4[0], hit)
                clips.append(mp4[0]); report["stages"][f"scene{i + 1}"] = {"wall_s": round(time.time() - t, 1), "exec_s": exe}
            say("music")
            t = time.time(); m = recipe["music"]
            outs, exe = runner.run(tape.load_graph(tape.WF_MUSIC, {"NAME": f"{tid}-music", "TAGS": m["tags"], "LYRICS": "[Instrumental]",
                                                                    "BPM": m["bpm"], "KEY": m["key"], "SECONDS": m["seconds"], "SEED": m["seed"]}), work)
            tracks = [o for o in outs if o.suffix in (".flac", ".mp3", ".wav")]
            if not tracks: raise TapeError("ACE-Step finished without an audio file")
            report["stages"]["music"] = {"wall_s": round(time.time() - t, 1), "exec_s": exe}
        report["peak_vram_mib"] = vram.peak
        say("tape")
        t = time.time()
        out = assemble(clips, tracks[0], recipe, work, out_dir / f"{tid}.mp4")
        report["stages"]["assemble"] = {"wall_s": round(time.time() - t, 1)}
    finally:
        report["vram"] = tape.free_vram(free_server); report["total_s"] = round(time.time() - t_all, 1)
        (work / "report.json").write_text(json.dumps(report, indent=1))
    report["file"] = str(out); report["probe"] = tape.probe(out)
    (out_dir / f"{tid}.json").write_text(json.dumps(report, indent=1))
    say("done", file=str(out))
    return out, report


def assemble(clips, music, recipe, work, out):
    """Grade each scene with its own stamp (a pause-cut glitch at the head of every scene after the first), join them,
    and lay ONE music track over the whole evening with each scene's own sound underneath and a click at each cut."""
    graded, lens = [], []
    date = datetime.date.today().strftime("%b %-d %Y").upper()
    for i, (clip, sc) in enumerate(zip(clips, recipe["scenes"])):
        info = tape.probe(clip)
        if not any(s["codec_type"] == "audio" for s in info["streams"]): raise TapeError(f"scene {i + 1} has no audio stream")
        g = work / f"graded-{i + 1}.mp4"
        tape._ff(["-i", str(clip), "-vf", tape.vhs_filter(recipe["label"] if i == 0 else None, f"{date}  {sc['time']}",
                                                         seed=sc["seed"], glitch=i > 0),
                  "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium", str(g)], f"grading scene {i + 1}")
        graded.append(g); lens.append(info["duration"])
    total = sum(lens); n = len(clips)
    if tape.probe(music)["duration"] < total: raise TapeError(f"the music is shorter than the evening ({total:.1f} s)")
    if tape.mean_volume(music) < -60: raise TapeError("the music track is silent")
    args = []
    for g in graded: args += ["-i", str(g)]
    for c in clips: args += ["-i", str(c)]
    args += ["-i", str(music)]
    cuts = [sum(lens[:k]) for k in range(1, n)]
    for _ in cuts: args += ["-f", "lavfi", "-i", CUT_CLICK]
    v = "".join(f"[{k}:v]" for k in range(n)) + f"concat=n={n}:v=1:a=0[vc];[vc]format=yuv420p[v]"
    amb = "".join(f"[{n + k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={tape.LTX_DUCK_DB}dB[s{k}];" for k in range(n))
    amb += "".join(f"[s{k}]" for k in range(n)) + f"concat=n={n}:v=0:a=1[amb]"
    mus = (f"[{2 * n}:a]aresample=48000,highpass=f=70,lowpass=f=4500,lowpass=f=4500,"
           "pan=stereo|c0=0.65*c0+0.35*c1|c1=0.35*c0+0.65*c1,acompressor=threshold=-22dB:ratio=2.5:attack=20:release=300,"
           f"loudnorm=I=-18:LRA=5:TP=-2,aresample=48000,atrim=0:{total:.3f},afade=t=in:d=1,afade=t=out:st={total - 4:.3f}:d=4[mus]")
    clk = "".join(f"[{2 * n + 1 + j}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(c * 1000)}|{int(c * 1000)}[c{j}];"
                  for j, c in enumerate(cuts))
    mix = "[mus][amb]" + "".join(f"[c{j}]" for j in range(len(cuts))) + \
          f"amix=inputs={2 + len(cuts)}:normalize=0:duration=first,alimiter=limit=0.89[a]"
    tmp = pathlib.Path(out).with_suffix(".part.mp4")
    tape._ff(args + ["-filter_complex", f"{v};{amb};{mus};{clk}{mix}", "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
                     "-metadata", f"comment={tape.AI_NOTICE}", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                     "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart+use_metadata_tags", str(tmp)], "joining the evening")
    tape.verify(tmp, total)
    tmp.replace(out)
    return pathlib.Path(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    mk = sub.add_parser("make"); mk.add_argument("--cast", required=True); mk.add_argument("--method", default="describe")
    mk.add_argument("--seed", type=int); mk.add_argument("--out", default=str(tape.HERE / "out" / "evening"))
    mk.add_argument("--server", default="http://127.0.0.1:8188"); mk.add_argument("--dry-run", action="store_true")
    mk.add_argument("--reseed", default="", help="new seeds for single scenes, e.g. 1=200,3=301 (others reuse the cache)")
    sub.add_parser("cast")
    a = ap.parse_args()
    try:
        if a.cmd == "cast":
            for k, v in CAST.items(): print(f"{k:14} {v['look']}")
            return
        reseed = {int(k): int(v) for k, v in (x.split("=") for x in a.reseed.split(",") if x)}
        recipe = plan_evening(a.cast, a.method, a.seed, reseed)
        if a.dry_run: print(json.dumps(recipe, indent=1)); return
        say = lambda stage, **kw: print(f"[{time.strftime('%H:%M:%S')}] {stage}", file=sys.stderr)
        out, rep = make_evening(recipe, tape.DirectComfy(a.server, 1200), a.out, say, free_server=a.server)
        print(json.dumps({"file": str(out), "total_s": rep["total_s"], "peak_vram_mib": rep["peak_vram_mib"], "stages": rep["stages"]}))
    except TapeError as e:
        print(f"evening: FAILED — {e}", file=sys.stderr); sys.exit(2)


if __name__ == "__main__":
    main()
