#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_DIR}/.venv-wsl/bin/activate"

hf download openai/clip-vit-base-patch32
hf download microsoft/trocr-small-printed
hf download google/owlvit-base-patch32
