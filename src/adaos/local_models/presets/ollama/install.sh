#!/usr/bin/env bash
set -euo pipefail
echo "[Ollama] Checking installation..."
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  # Refer to official install instructions for Linux/macOS
  if [[ "$OSTYPE" == darwin* ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install ollama || true
    elif command -v curl >/dev/null 2>&1; then
      curl -fsSL https://ollama.ai/install.sh | sh || true
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://ollama.ai/install.sh | sh || true
    else
      echo "Neither brew, curl nor wget is available. Please install Ollama manually: https://ollama.ai"
    fi
  else
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL https://ollama.ai/install.sh | sh || true
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://ollama.ai/install.sh | sh || true
    else
      echo "Neither curl nor wget is available. Please install Ollama manually: https://ollama.ai"
    fi
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama not found. Please install from https://ollama.ai"
  exit 1
fi

echo "Starting ollama serve in background (if not running)..."
(ollama serve >/dev/null 2>&1 &) || true
sleep 2

models=(
  "llama3.2:3b-instruct" "llama3.1:8b-instruct" "qwen2.5:7b-instruct" "qwen2.5:3b-instruct"
  "mistral:7b-instruct" "phi3:mini" "gemma2:2b-instruct" "neural-chat:7b-v3.3" "openhermes:2.5-mistral"
)
for m in "${models[@]}"; do
  echo "ollama pull $m"
  ollama pull "$m" || true
done
echo "Done. Base URL: http://127.0.0.1:11434/v1"
