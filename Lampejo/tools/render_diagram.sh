#!/usr/bin/env bash
# render_diagram.sh — turn a .drawio / mxGraph XML file into a high-res PNG.
#
# Usage:
#   ./render_diagram.sh <input.drawio> <output.png> [--transparent] [--scale N] [--border N]
#
# Defaults: white background, scale 2 (retina), border 20px.
# Verifies the PNG actually exists and is non-trivial before exiting 0.
#
# This is the render step of the "diagram-from-anything" global skill.
set -euo pipefail

IN="${1:-}"
OUT="${2:-}"
shift 2 2>/dev/null || true

if [[ -z "$IN" || -z "$OUT" ]]; then
  echo "ERROR: usage: render_diagram.sh <input.drawio> <output.png> [--transparent] [--scale N] [--border N]" >&2
  exit 2
fi
if [[ ! -f "$IN" ]]; then
  echo "ERROR: input file not found: $IN" >&2
  exit 2
fi

SCALE=2
BORDER=20
TRANSPARENT=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --transparent) TRANSPARENT=1; shift ;;
    --scale) SCALE="$2"; shift 2 ;;
    --border) BORDER="$2"; shift 2 ;;
    *) echo "WARN: unknown arg $1 (ignored)" >&2; shift ;;
  esac
done

# --- 1. Resolve the drawio binary -------------------------------------------
DRAWIO="${LSL_DRAWIO:-}"
if [[ -z "$DRAWIO" ]]; then
  if command -v drawio >/dev/null 2>&1; then DRAWIO="$(command -v drawio)"
  elif [[ -x "/Applications/draw.io.app/Contents/MacOS/draw.io" ]]; then DRAWIO="/Applications/draw.io.app/Contents/MacOS/draw.io"
  fi
fi
if [[ -z "$DRAWIO" ]]; then
  echo "ERROR: draw.io nao encontrado. Rode o setup do Lampejo de novo (ele instala o draw.io)." >&2
  exit 3
fi
echo "using drawio: $DRAWIO" >&2

mkdir -p "$(dirname "$OUT")"

TRANSFLAG=()
[[ "$TRANSPARENT" == "1" ]] && TRANSFLAG=(--transparent)

# --- 2. Portable timeout wrapper (no coreutils on macOS) --------------------
# Runs the export in the background and kills it if it exceeds TIMEOUT seconds.
run_export() {
  local timeout_s=90
  rm -f "$OUT"
  "$DRAWIO" --export --format png --scale "$SCALE" --border "$BORDER" \
    ${TRANSFLAG[@]+"${TRANSFLAG[@]}"} --output "$OUT" "$IN" >"${TMPDIR:-/tmp}/drawio_render.log" 2>&1 &
  local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [[ "$waited" -ge "$timeout_s" ]]; then
      kill -9 "$pid" 2>/dev/null || true
      echo "ERROR: drawio export timed out after ${timeout_s}s" >&2
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  wait "$pid" 2>/dev/null || true
  return 0
}

# --- 3. Attempt render, with a --no-sandbox / --disable-gpu retry ------------
run_export || true

if [[ ! -s "$OUT" ]]; then
  echo "first attempt produced no output — retrying with --no-sandbox --disable-gpu…" >&2
  rm -f "$OUT"
  "$DRAWIO" --export --format png --scale "$SCALE" --border "$BORDER" \
    "${TRANSFLAG[@]}" --no-sandbox --disable-gpu \
    --output "$OUT" "$IN" >"${TMPDIR:-/tmp}/drawio_render.log" 2>&1 || true
fi

# --- 4. Verify --------------------------------------------------------------
if [[ ! -s "$OUT" ]]; then
  echo "ERROR: render failed — no PNG produced. Log:" >&2
  cat "${TMPDIR:-/tmp}/drawio_render.log" >&2 || true
  exit 4
fi

# Must be a real PNG, not a stub
if ! file "$OUT" | grep -qi "PNG image"; then
  echo "ERROR: output exists but is not a valid PNG:" >&2
  file "$OUT" >&2
  exit 4
fi

DIMS="$(sips -g pixelWidth -g pixelHeight "$OUT" 2>/dev/null | grep -E 'pixel' | awk '{print $2}' | paste -sd'x' -)"
BYTES="$(wc -c < "$OUT" | tr -d ' ')"
echo "OK: $OUT (${DIMS:-unknown} px, ${BYTES} bytes)"
