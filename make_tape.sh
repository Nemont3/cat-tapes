#!/usr/bin/env bash
# make_tape.sh "<prompt>" [preset] — one lofi VHS cat tape: LTX-2.5 clip → ACE-Step lofi → mix → VHS grade → one MP4.
# An empty prompt with a preset makes that preset's tape. Extra flags pass through to `tape.py make` (e.g. --seed 7,
# --server URL, --stamp "OCT 29 1996  4:12 PM", --dry-run). Exits non-zero with the reason on any failure.
set -euo pipefail
cd "$(dirname "$0")"
PROMPT=${1:-}; [[ $# -gt 0 ]] && shift
PRESET=; if [[ $# -gt 0 && $1 != -* ]]; then PRESET=$1; shift; fi
exec python3 tape.py make --prompt "$PROMPT" ${PRESET:+--preset "$PRESET"} "$@"
