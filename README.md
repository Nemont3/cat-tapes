# CAT TAPES 📼🐈

**Press a tape, get a cozy lofi cat video that looks like it was filmed on a camcorder in 1996.**

▶ **Watch:** [the demo (1:32)](https://youtu.be/-0cfz9QJGxU) · more in [samples/](samples/README.md)

cat-tape is a small local web app built on ComfyUI. Pick a cassette from the shelf or describe a cat moment in your own
words. A few minutes later a 10-second tape comes out: an LTX-2.5 clip with
its own sound, a soft generated lofi track on top, and a home-video VHS look with a blinking `PLAY ▶` and a date stamp.

Everything runs on your own GPU with open weights: no cloud needed, no API keys, no partner nodes.
Or try it in your browser: [Comfy Cloud](https://cloud.comfy.org/?share=df687c5f4ce0) (a simplified edition; it runs on your Comfy account).

## An evening tape (40 seconds)

One tap gives one cat's afternoon outside: **tall grass → dandelions → the fence top → the sunset**. Four 10-second
LTX-2.5 scenes, cut together like a camcorder paused and restarted (a burst of tape noise, a blinking `● REC`), with
the date stamp moving on from 4:48 PM to 6:31 PM and **one** lofi track carrying the whole thing. Pick the cat:

- **the little black cat** with a bright pink collar and a silver bell
- **the fluffy orange cat** with a cream chest ruff
- **the black cat with white socks**

The same cat in every scene comes from a fixed, detailed description repeated in each scene's prompt. (We tested
starting each scene from the previous scene's last frame instead: the cat held just as well, but every scene began in
the last scene's place, so the cuts stopped reading as cuts.)

```bash
python3 evening.py make --cast orange-fluff
```

## The tapes

| cassette | what's on it |
|---|---|
| SUNBEAM NAP | a tabby asleep in a square of afternoon sun, belly rising and falling |
| RAIN ON THE WINDOW | a black cat watching raindrops race down the glass |
| BLANKET LOAF | a perfect loaf on a knit blanket, one slow blink |
| 3AM ZOOMIES | a kitten skidding down a dark hallway after a sock |
| CARDBOARD CASTLE | a kitten finds a box, climbs in, peeks out |
| FIRST SNOW | a kitten batting at the first snowflakes |

Or write your own: "a kitten discovers its own reflection in a puddle…"

The page is a 1980s den at night (two backdrops rendered locally with **Z-Image Turbo**, open weights). While a tape
records, the room dims and the TV becomes the light.

## How it works

```
 preset / your words
        │
        ▼
 LTX-2.5 22B (distilled)  ──►  10 s of video + its own sound (purrs, rain, paws)
        ▼
 ACE-Step 1.5 XL turbo    ──►  a sparse lofi track (felt piano, warm pad, no drums)
        │
        ▼
 mix: the music on top, LTX's own sound ducked underneath
        │
        ▼
 the VHS effect (ffmpeg): 640×480 4:3 picture, chroma bleed, tape noise, soft blur,
 vignette, scanlines, PLAY ▶, a date stamp, and the cassette's label for the first second
        │
        ▼
 one MP4, 1440×1080 (the 640×480 look, delivered sharp)
```

**The VFX is the camcorder tape.** LTX-2.5 makes the picture and the sound. The effect turns that into a home video:
it separates and offsets the red and blue channels so the colour bleeds like tape, adds animated grain, softens and
vignettes the picture, then rescales it with nearest-neighbour so the scanline grid stays crisp.

The generation graphs (`workflows/ltx25_t2v.json`, `workflows/ace15_music.json`)
use **only ComfyUI's built-in nodes**, no custom nodes. The app reaches ComfyUI through Comfy's own
[`comfy-sdk`](https://pypi.org/project/comfy-sdk/) and [`comfy-api-proxy`](https://pypi.org/project/comfy-api-proxy/).
The VHS step is ffmpeg, because ComfyUI's built-in nodes have no chroma-offset or scanline filter.

## Run it locally

**You need:** ComfyUI ≥ 0.37.4 (tested on 0.37.4), an NVIDIA GPU with 24 GB (on an RTX 3090 the LTX clip takes
about 2 minutes), Python 3 (tested on 3.14), and ffmpeg.

### 1 · Models (into ComfyUI's `models/` folders)

| file | folder | from |
|---|---|---|
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `diffusion_models/` | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) `diffusion_models/` |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders/` | Lightricks/LTX-2.5 `text_encoders/` |
| `ltx-2.5-video-vae-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` | `vae/` | Lightricks/LTX-2.5 `vae/` |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` | Lightricks/LTX-2.5 `latent_upscale_models/` |
| `acestep_v1.5_xl_turbo_bf16.safetensors` | `diffusion_models/` | [Comfy-Org/ace_step_1.5_ComfyUI_files](https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files) `split_files/diffusion_models/` |
| `qwen_0.6b_ace15.safetensors`, `qwen_4b_ace15.safetensors` | `text_encoders/` | same, `split_files/text_encoders/` |
| `ace_1.5_vae.safetensors` | `vae/` | same, `split_files/vae/` |

Downloading the LTX-2.5 weights means accepting the LTX-2.x Community License (see [Licences](#licences)).

Check that your ComfyUI sees every node and file the graphs need, without rendering anything:

```bash
python3 tests/check_graphs.py http://127.0.0.1:8188
```

### 2a · The app (the tape deck)

```bash
python3 -m venv .venv && .venv/bin/pip install "comfy-sdk==0.5.0" "comfy-api-proxy==0.1.6"
export COMFY_API_PROXY_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(24))")

# terminal 1: the proxy, loopback only, with a token
.venv/bin/comfy-api-proxy run --host 127.0.0.1 --port 8189 --comfyui http://127.0.0.1:8188 --token "$COMFY_API_PROXY_TOKEN"

# terminal 2: the app
COMFY_BASE_URL=http://127.0.0.1:8189 COMFY_ROUTER_BASE_URL=http://127.0.0.1:9 CAT_TAPE_OUT=$PWD/out/app \
  .venv/bin/python -I app/server.py --port 8190
```

Open <http://127.0.0.1:8190/>. The app listens on 127.0.0.1 only. It refuses to start if the SDK could reach
anything other than your own machine: a non-loopback base URL, a `COMFY_API_KEY`, or a `*_PROXY` variable.
`COMFY_ROUTER_BASE_URL` points at a dead local port on purpose, so nothing can fall through to a cloud default.

### 2b · Or one command, no web page

```bash
./make_tape.sh "" sunbeam-nap                       # a preset
./make_tape.sh "a kitten chasing a butterfly"       # your own words
./make_tape.sh "" 3am-zoomies --seed 7 --stamp "OCT 29 1996  4:12 PM"
```

This needs only Python and ffmpeg, and talks to ComfyUI directly on `127.0.0.1:8188`. The tape lands in `out/`,
next to a JSON report (seeds, timings, peak VRAM).

Every failure stops with the reason and a non-zero exit, and never leaves an empty file: ComfyUI down, a node or
model missing, a timeout, a missing output, a silent track. `tests/test_fail_loud.sh` checks this without a GPU.

## Licences

- **cat-tape's own code** (`*.py`, `*.sh`, `app/`, `presets.json`, the workflow JSON): MIT, see `LICENSE`.
- **LTX-2.5** (Lightricks): the [LTX-2.x Community License Agreement](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x).
  This repo does not include or redistribute the weights; you download them from Lightricks and accept the licence
  there. Its use restrictions (Attachment A and the Acceptable Use Policy) apply to what you make with it.
- **ACE-Step 1.5 XL turbo** (the ACE-Step team): MIT on its [model card](https://huggingface.co/ACE-Step/acestep-v15-xl-turbo).
- Notes and the exact clauses that matter for this app: `LICENSES-MODELS.md`.
- **The model weights this software drives are NOT covered by the MIT licence:** LTX-2.5 is under the LTX-2.x
  Community License Agreement, ACE-Step 1.5 under MIT, Z-Image Turbo (the page backdrop) under Apache-2.0.

**Everything cat-tape makes is AI-generated.** Every tape carries that in its metadata, and anything you post
should say so (the LTX-2.x licence asks for it).

## Made for

Comfy's **Open Source Higgsfield** challenge (October 2026), #OpenSourceHiggsfield.
