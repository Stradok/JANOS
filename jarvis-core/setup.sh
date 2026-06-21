#!/usr/bin/env bash
# ============================================================
#  JAN — Joint Autonomous Neural Agent
#  Linux / macOS Setup Script
#  Usage: chmod +x setup.sh && ./setup.sh
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; }
info() { echo -e "${CYAN}[i]${NC} $1"; }
hr()   { echo -e "${DIM}────────────────────────────────────────${NC}"; }

echo ""
echo -e "${CYAN}  ╔═══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║    JAN — Joint Autonomous Neural Agent   ║${NC}"
echo -e "${CYAN}  ║         Linux / macOS Setup               ║${NC}"
echo -e "${CYAN}  ╚═══════════════════════════════════════════╝${NC}"
echo ""

# --------------------------------------------------
#  1. Check Python 3.10+
# --------------------------------------------------
hr
info "Checking Python version..."
PY_VER=$(python3 --version 2>/dev/null || python --version 2>/dev/null || true)
if [ -z "$PY_VER" ]; then
    err "Python not found! Install Python 3.10+ first."
    echo "  https://www.python.org/downloads/"
    exit 1
fi
log "Found $PY_VER"

# Extract major.minor
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)' 2>/dev/null || python -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || python -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    err "Python 3.10+ required. Found $PY_MAJOR.$PY_MINOR"
    exit 1
fi

# --------------------------------------------------
#  2. System Dependencies
# --------------------------------------------------
hr
info "Installing system dependencies..."

OS="$(uname -s)"
case "$OS" in
    Linux)
        if command -v apt &>/dev/null; then
            log "Detected apt-based Linux"
            sudo apt update
            sudo apt install -y ffmpeg tesseract-ocr portaudio19-dev python3-tk python3-dev
        elif command -v pacman &>/dev/null; then
            log "Detected pacman-based Linux"
            sudo pacman -Sy --noconfirm ffmpeg tesseract portaudio tk python
        elif command -v dnf &>/dev/null; then
            log "Detected dnf-based Linux"
            sudo dnf install -y ffmpeg tesseract portaudio-devel python3-tkinter
        else
            warn "Unknown package manager. Install manually:"
            warn "  ffmpeg, tesseract-ocr, portaudio, python3-tk"
        fi
        ;;
    Darwin)
        if command -v brew &>/dev/null; then
            log "Detected macOS with Homebrew"
            brew install ffmpeg tesseract portaudio
        else
            warn "Homebrew not found. Install from https://brew.sh or install manually:"
            warn "  ffmpeg, tesseract, portaudio"
        fi
        ;;
    *)
        warn "Unknown OS '$OS'. Install dependencies manually:"
        warn "  ffmpeg, tesseract-ocr, portaudio"
        ;;
esac
log "System dependencies done."

# --------------------------------------------------
#  3. Create Virtual Environment
# --------------------------------------------------
hr
info "Setting up Python virtual environment..."
if [ -d "venv" ]; then
    warn "venv/ already exists — skipping creation."
else
    python3 -m venv venv || python -m venv venv
    log "Virtual environment created."
fi

# Activate
source venv/bin/activate || source venv/Scripts/activate 2>/dev/null || true
log "Virtual environment activated."

# Upgrade pip
pip install --upgrade pip
log "pip upgraded."

# --------------------------------------------------
#  4. Install Python Dependencies
# --------------------------------------------------
hr
info "Installing Python packages..."
if [ -f "requirements_full.txt" ]; then
    pip install -r requirements_full.txt
elif [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    warn "No requirements file found — skipping pip install."
fi
log "Python packages installed."

# --------------------------------------------------
#  5. Create Runtime Directories
# --------------------------------------------------
hr
info "Creating runtime directories..."
mkdir -p memory/audio/tts
mkdir -p memory/vision/faces
mkdir -p memory/vision/captures
mkdir -p memory/vision/voices
mkdir -p memory/logs
mkdir -p modules/generated
log "Runtime directories created."

# --------------------------------------------------
#  6. Check Ollama
# --------------------------------------------------
hr
info "Checking Ollama..."
if command -v ollama &>/dev/null; then
    log "Ollama found."
    echo ""
    echo -e "  ${YELLOW}Recommended: Pull your LLM models now.${NC}"
    echo -e "  ${DIM}  Example: ollama pull <your-model-name>${NC}"
    echo -e "  ${DIM}  Edit config.yaml to set your models under 'models:'${NC}"
    echo ""
    read -rp "  Pull models now? (y/N): " PULL_MODELS
    if [[ "$PULL_MODELS" =~ ^[Yy]$ ]]; then
        echo ""
        read -rp "  Model name to pull (e.g. llama3.1:8b): " MODEL_NAME
        if [ -n "$MODEL_NAME" ]; then
            ollama pull "$MODEL_NAME"
            log "Model '$MODEL_NAME' pulled."
        fi
    fi
else
    warn "Ollama not found."
    echo "  Install it from: https://ollama.com"
    echo "  Then pull your model, e.g.:"
    echo "    ollama pull <your-model>"
    echo "  And set it in config.yaml under 'models:'"
fi

# --------------------------------------------------
#  7. Optional: Face Recognition
# --------------------------------------------------
hr
info "Optional: Face / voice recognition (needs cmake + dlib)"
read -rp "  Install face-recognition + resemblyzer? (y/N): " INSTALL_FACE
if [[ "$INSTALL_FACE" =~ ^[Yy]$ ]]; then
    pip install face-recognition resemblyzer
fi

# --------------------------------------------------
#  8. Optional: Wake Word
# --------------------------------------------------
hr
info "Optional: Wake word detection (always-listening 'Hey JAN')"
read -rp "  Install pyaudio + openwakeword? (y/N): " INSTALL_WAKE
if [[ "$INSTALL_WAKE" =~ ^[Yy]$ ]]; then
    pip install pyaudio openwakeword
fi

# --------------------------------------------------
#  Done
# --------------------------------------------------
hr
echo ""
echo -e "${GREEN}  ╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}  ║         Setup Complete!                   ║${NC}"
echo -e "${GREEN}  ╚═══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}Run JAN in terminal:${NC}"
echo -e "    source venv/bin/activate"
echo -e "    python demo.py"
echo ""
echo -e "  ${CYAN}Run JAN as server:${NC}"
echo -e "    source venv/bin/activate"
echo -e "    uvicorn main:app --host 0.0.0.0 --port 8000"
echo ""
echo -e "  ${CYAN}Make sure Ollama is running with your model:${NC}"
echo -e "    ollama serve"
echo ""
echo -e "  ${DIM}Edit config.yaml to set your models, features, and settings.${NC}"
echo ""
