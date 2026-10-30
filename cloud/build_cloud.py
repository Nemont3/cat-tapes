#!/usr/bin/env python3
"""build_cloud.py — generate the Comfy Cloud edition: ONE workflow, ComfyUI core nodes only (the cloud has no custom
nodes and none of our ffmpeg). Output: cat-tapes-cloud.json (API format; ComfyUI's editor opens it directly, node titles from _meta).

  LTX-2.5 text-to-video (our tested graph, the official template's file names)
  ACE-Step 1.5 XL turbo lofi (our tested graph)
  audio: LTX's own sound −12 dB, music added on top, trimmed to the clip (AudioMerge)
  VHS look from core image nodes: 640×480 4:3, red/green/blue channels offset (multiply by pure-colour images, screen
  back together), blur, grain, contrast, PLAY > (the default font has no ▶) and a date stamp (TextOverlay), nearest-neighbour up to 1440×1080.
  Not reproduced from the ffmpeg grade: vignette, scanline grid, saturation lift, the music's fades and loudness finish.
"""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import tape  # noqa: E402

PRESET = "sunbeam-nap"
DATE_STAMP = "OCT 29 1996  4:12 PM"   # a fixed camcorder date: the cloud has no clock node


def build():
    p = tape.load_presets()[PRESET]
    recipe = tape.plan_tape(None, PRESET)
    subs = {"NAME": "cat-tape", "PROMPT": recipe["video"]["prompt"], "NEGATIVE": tape.NEGATIVE, "SEED": p["seed"],
            "ASPECT": "4:3 (Standard)", "SECONDS": tape.TAPE_SECONDS}
    video = tape.load_graph(tape.WF_VIDEO, subs)
    m = recipe["music"]
    music = tape.load_graph(tape.WF_MUSIC, {"NAME": "cat-tape", "TAGS": m["tags"], "LYRICS": "[Instrumental]",
                                            "BPM": m["bpm"], "KEY": m["key"], "SECONDS": m["seconds"], "SEED": m["seed"]})
    g = {}
    # 1 · LTX-2.5 (drop our SaveVideo/CreateVideo; the tape is assembled below). Official model file names.
    for nid, n in video.items():
        if n["class_type"] in ("SaveVideo", "CreateVideo"): continue
        g["v" + nid.replace("405:", "")] = n
    relink(g, "v", "405:")
    # 2 · ACE-Step 1.5 XL turbo (drop its SaveAudio)
    for nid, n in music.items():
        if n["class_type"].startswith("SaveAudio"): continue
        g["m" + nid] = n
    relink(g, "m", "", only="m")
    frames, ltx_audio, fps, ace = ["v374", 0], ["v358", 0], ["v359", 0], ["m18", 0]

    def node(nid, ct, title, **inputs):
        g[nid] = {"class_type": ct, "inputs": inputs, "_meta": {"title": title}}
        return [nid, 0]

    # 3 · the tape's sound
    duck = node("a1", "AudioAdjustVolume", "LTX sound, ducked under the music", audio=ltx_audio, volume=tape.LTX_DUCK_DB)
    mix = node("a2", "AudioMerge", "music on top (trimmed to the clip)", audio1=duck, audio2=ace, merge_method="add")
    # 4 · the VHS look, core nodes only
    sd = node("h1", "ImageScale", "camcorder frame: 640×480, 4:3", image=frames, upscale_method="area", width=640, height=480, crop="center")
    chans = []
    for i, (name, x, colour) in enumerate([("red", 6, 0xFF0000), ("green", 3, 0x00FF00), ("blue", 0, 0x0000FF)]):
        c = node(f"h2{name[0]}", "ImageCrop", f"{name} channel, shifted {x} px", image=sd, width=634, height=480, x=x, y=0)
        k = node(f"h3{name[0]}", "EmptyImage", f"pure {name}", width=634, height=480, batch_size=1, color=colour)
        chans.append(node(f"h4{name[0]}", "ImageBlend", f"keep only {name}", image1=c, image2=k, blend_factor=1.0, blend_mode="multiply"))
    rg = node("h5", "ImageBlend", "red + green (colour bleed)", image1=chans[0], image2=chans[1], blend_factor=1.0, blend_mode="screen")
    rgb = node("h6", "ImageBlend", "+ blue (colour bleed)", image1=rg, image2=chans[2], blend_factor=1.0, blend_mode="screen")
    back = node("h7", "ImageScale", "back to 640×480", image=rgb, upscale_method="bicubic", width=640, height=480, crop="disabled")
    soft = node("h8", "ImageBlur", "tape softness", image=back, blur_radius=2, sigma=1.2)
    grain = node("h9", "ImageAddNoise", "tape grain", image=soft, seed=7, strength=0.04)
    con = node("h10", "AdjustContrast", "a little contrast", images=grain, factor=1.05)
    play = node("h11", "TextOverlay", "PLAY >", images=con, text="PLAY  >", font_size=4.5, color="#ffffff",
                position="top", align="left", outline=True)
    stamp = node("h12", "TextOverlay", "date stamp", images=play, text=DATE_STAMP, font_size=4.5, color="#ffffff",
                 position="bottom", align="right", outline=True)
    big = node("h13", "ImageScale", "up to 1440×1080, hard pixels", image=stamp, upscale_method="nearest-exact", width=1440, height=1080, crop="disabled")
    # 5 · the tape
    vid = node("t1", "CreateVideo", "the tape", images=big, fps=fps, audio=mix)
    node("t2", "SaveVideo", "save the tape", video=vid, filename_prefix="cat-tape/tape", format="mp4", **{"format.codec": "h264"})
    return g


def relink(g, prefix, old, only=None):
    """Rewrite links to the renamed node ids."""
    for nid, n in g.items():
        if only and not nid.startswith(only): continue
        for k, v in n["inputs"].items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                src = v[0][len(old):] if old and v[0].startswith(old) else v[0]
                n["inputs"][k] = [prefix + src, v[1]]


if __name__ == "__main__":
    out = HERE / "cat-tapes-cloud.json"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False))
    print(out)
