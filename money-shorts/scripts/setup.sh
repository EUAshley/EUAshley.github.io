#!/usr/bin/env bash
# One-time setup: system tools, Python deps, and the local Kokoro TTS model.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v ffmpeg >/dev/null; then
  sudo_cmd=""; [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
  $sudo_cmd apt-get update && $sudo_cmd apt-get install -y --no-install-recommends ffmpeg espeak-ng
fi
pip install -r requirements.txt

MODELS="${MONEYSHORTS_MODELS:-models}"
mkdir -p "$MODELS"
base=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -f "$MODELS/kokoro-v1.0.onnx" ] || curl -fL -o "$MODELS/kokoro-v1.0.onnx" "$base/kokoro-v1.0.onnx"
[ -f "$MODELS/voices-v1.0.bin" ]  || curl -fL -o "$MODELS/voices-v1.0.bin"  "$base/voices-v1.0.bin"
echo "Setup complete. Try: python -m moneyshorts check episodes/costco-membership.yaml"
