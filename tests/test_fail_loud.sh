#!/usr/bin/env bash
# test_fail_loud.sh — every failure stops non-zero with its reason; the good path makes a verified tape.
# Uses NO GPU: a dead port, a graph ComfyUI rejects at validation, and the ffmpeg half on synthetic clips.
set -uo pipefail
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; fail=0
expect_fail() {  # <name> <expected reason regex> <command…>
  local name=$1 want=$2; shift 2
  out=$("$@" 2>&1); rc=$?
  if [[ $rc -ne 0 && $out =~ $want ]]; then echo "ok   $name — exit $rc: $(grep -m1 -o 'FAILED.*' <<<"$out" | cut -c1-140)"; ((pass++))
  else echo "FAIL $name — exit $rc, wanted /$want/, got: ${out:0:300}"; ((fail++)); fi
}
expect_ok() {
  local name=$1; shift
  out=$("$@" 2>&1); rc=$?
  if [[ $rc -eq 0 ]]; then echo "ok   $name"; ((pass++)); else echo "FAIL $name — exit $rc: ${out:0:300}"; ((fail++)); fi
}
ff() { ffmpeg -v error -y "$@"; }
# synthetic stand-ins: an "LTX clip" 1280×704 5 s with sound, a 12 s "music" track, and the broken variants
ff -f lavfi -i testsrc2=s=1280x704:r=24:d=5.04 -f lavfi -i sine=f=220:d=5.04 -c:v libx264 -c:a aac -shortest "$T/clip.mp4"
ff -f lavfi -i testsrc2=s=1280x704:r=24:d=5.04 -c:v libx264 "$T/clip-mute.mp4"
ff -f lavfi -i testsrc2=s=1088x832:r=24:d=5.04 -f lavfi -i sine=f=220:d=5.04 -c:v libx264 -c:a aac -shortest "$T/clip43.mp4"   # the real 4:3 render size
ff -f lavfi -i sine=f=330:d=12 "$T/music.flac"
ff -f lavfi -i anullsrc=r=48000:cl=stereo -t 12 "$T/music-silent.flac"
ff -f lavfi -i sine=f=330:d=2 "$T/music-short.flac"

expect_fail "dead ComfyUI port"        "unreachable"            python3 tape.py make --preset sunbeam-nap --server http://127.0.0.1:9 --out "$T/out"
expect_fail "bad graph"                "rejected|refused"       python3 -c "
import sys, tape
try: tape.DirectComfy('http://127.0.0.1:8188').run({'1': {'class_type': 'NoSuchNode_catTape', 'inputs': {}}}, '$T')
except tape.TapeError as e: print('cat-tape: FAILED —', e); sys.exit(2)"
expect_fail "unfilled placeholder"     "placeholder"            python3 -c "
import sys, tape
try: tape.load_graph('workflows/ltx25_t2v.json', {'NAME': 'x'})
except tape.TapeError as e: print('cat-tape: FAILED —', e); sys.exit(2)"
expect_fail "unknown preset"           "no preset"              python3 tape.py make --preset nope --dry-run
expect_fail "no prompt, no preset"     "give a prompt"          python3 tape.py make --dry-run
expect_fail "over-long prompt"         "limit is"               python3 tape.py make --prompt "$(printf 'cat %.0s' {1..200})" --dry-run
expect_fail "clip without sound"       "no audio stream"        python3 tape.py post "$T/clip-mute.mp4" "$T/music.flac" "$T/x.mp4"
expect_fail "silent music"             "silent"                 python3 tape.py post "$T/clip.mp4" "$T/music-silent.flac" "$T/x.mp4"
expect_fail "music shorter than clip"  "shorter"                python3 tape.py post "$T/clip.mp4" "$T/music-short.flac" "$T/x.mp4"
expect_fail "missing input file"       "cannot read"            python3 tape.py post "$T/nope.mp4" "$T/music.flac" "$T/x.mp4"
echo "not an image" > "$T/fake.jpg"
ff -f lavfi -i testsrc2=s=900x1600 -frames:v 1 -metadata comment=SECRET-GPS "$T/portrait.jpg"
expect_fail "photo that is not an image" "JPEG, PNG or WebP"   python3 tape.py make --photo "$T/fake.jpg" --server http://127.0.0.1:9 --out "$T/out"
expect_fail "photo, dead ComfyUI port"   "unreachable"         python3 tape.py make --photo "$T/portrait.jpg" --server http://127.0.0.1:9 --out "$T/out"
expect_ok   "photo prepared to 4:3, metadata stripped"         python3 -c "
import tape, subprocess, sys
p = tape.prepare_photo('$T/portrait.jpg', '$T/prep.png'); i = tape.probe(p)['streams'][0]
meta = subprocess.run(['ffprobe','-v','error','-show_entries','format_tags','-of','json',str(p)],capture_output=True,text=True).stdout
assert (i['width'], i['height']) == (1536, 1152), i; assert 'SECRET' not in meta, meta"
expect_ok   "good path, real 4:3 render size 1088×832"     python3 tape.py post "$T/clip43.mp4" "$T/music.flac" "$T/good43.mp4"
expect_ok   "good path (synthetic)"                             python3 tape.py post "$T/clip.mp4" "$T/music.flac" "$T/good.mp4" --label "SUNBEAM NAP" --stamp "OCT 29 1996  4:12 PM"
[[ -e "$T/x.mp4" || -e "$T/x.part.mp4" ]] && { echo "FAIL a failed run left a file behind"; ((fail++)); } || { echo "ok   no file left by failed runs"; ((pass++)); }
if [[ -s "$T/good.mp4" ]]; then ffprobe -v error -show_entries stream=codec_type,width,height:format=duration -of compact "$T/good.mp4"; fi
echo "— $pass passed, $fail failed"; [[ $fail -eq 0 ]]
