#!/usr/bin/env python3
"""make_backdrops.py — the app page's den backdrops, rendered locally with Z-Image Turbo (open weights).
Writes candidates to out/backdrop/; the picks are converted to app/static/*.webp by hand-chosen seed."""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tape

WF = pathlib.Path(__file__).resolve().parent / "zimage_turbo_t2i.json"
LOOK = "Warm, cozy, low amber light, soft and slightly hazy like old 35mm film, gentle film grain, no people, no text, no logos."
SCENES = {
    "den-scene": ("A cozy 1980s home den with dark walnut wood-panelled walls, wide shot. A warm amber table lamp glows at the "
                  "bottom-left edge of the frame. A small framed landscape painting and the edge of a wooden bookshelf at the "
                  "right edge. The centre of the wall is plain, dark and empty. " + LOOK),
    "den-wall": ("A plain dark walnut wood-panelled wall of a 1980s den, two brass wall sconces glowing warmly at the far left "
                 "and far right edges, the centre plain, dark and empty. " + LOOK),
}

def main(seeds=(11, 22, 33, 44), out=tape.HERE / "out" / "backdrop"):
    out.mkdir(parents=True, exist_ok=True); r = tape.DirectComfy()
    for name, prompt in SCENES.items():
        for s in seeds:
            files, exe = r.run(tape.load_graph(WF, {"PROMPT": prompt, "SEED": s, "W": 1920, "H": 1088, "NAME": f"{name}-{s}"}), out)
            print(name, s, exe, [f.name for f in files], flush=True)
    print(tape.free_vram())

if __name__ == "__main__":
    main()
