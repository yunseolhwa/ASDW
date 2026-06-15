#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/.venv-wsl"
ROCM_VERSION="$(cat /opt/rocm/.info/version 2>/dev/null || true)"

python3 -m venv "${VENV_DIR}"
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip==26.1.2 wheel==0.47.0 setuptools==70.2.0

case "${ROCM_VERSION}" in
  7.2*|"")
    TORCH_INDEX="https://download.pytorch.org/whl/rocm7.2"
    TORCH_SPEC=(torch==2.11.0 torchvision==0.26.0 torchaudio==2.11.0)
    ;;
  7.1*)
    TORCH_INDEX="https://download.pytorch.org/whl/rocm7.1"
    TORCH_SPEC=(torch==2.10.0 torchvision==0.25.0 torchaudio==2.10.0)
    ;;
  6.4*)
    TORCH_INDEX="https://download.pytorch.org/whl/rocm6.4"
    TORCH_SPEC=(torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1)
    ;;
  *)
    echo "Unsupported or unverified ROCm version: ${ROCM_VERSION}" >&2
    echo "Set TORCH_INDEX and TORCH_VERSION manually, or edit this script." >&2
    exit 2
    ;;
esac

python -m pip install "${TORCH_SPEC[@]}" --index-url "${TORCH_INDEX}"
python -m pip install -r "${PROJECT_DIR}/requirements-wsl-rocm.txt"

python - <<'PY'
import torch

print("torch:", torch.__version__)
print("cuda_available_for_rocm:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device:", torch.cuda.get_device_name(0))
PY
