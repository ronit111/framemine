#!/usr/bin/env bash
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { printf "${BOLD}%s${NC}\n" "$*"; }
success() { printf "${GREEN}%s${NC}\n" "$*"; }
warn()    { printf "${YELLOW}WARNING: %s${NC}\n" "$*"; }
error()   { printf "${RED}ERROR: %s${NC}\n" "$*"; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

info "Setting up framemine..."
echo ""

# ── Python 3.10+ ──────────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    error "python3 not found. Install Python 3.10+ and try again."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    error "Python 3.10+ required (found $PY_VERSION)."
    exit 1
fi

success "Python $PY_VERSION found."

# ── ffmpeg ─────────────────────────────────────────────────────────────

if command -v ffmpeg &>/dev/null; then
    FFMPEG_VER=$(ffmpeg -version 2>&1 | head -n1 | awk '{print $3}')
    success "ffmpeg $FFMPEG_VER found."
else
    warn "ffmpeg not found. framemine requires ffmpeg for frame extraction."
    echo "  Install:"
    echo "    macOS:  brew install ffmpeg"
    echo "    Ubuntu: sudo apt install ffmpeg"
    echo "    Other:  https://ffmpeg.org/download.html"
    echo ""
fi

# ── yt-dlp (optional) ─────────────────────────────────────────────────

if command -v yt-dlp &>/dev/null; then
    success "yt-dlp found."
else
    warn "yt-dlp not found. Needed only for downloading from URLs or TikTok/YouTube."
    echo "  Install:"
    echo "    pip install yt-dlp"
    echo "    or: brew install yt-dlp"
    echo ""
fi

# ── instaloader (optional) ───────────────────────────────────────────

if command -v instaloader &>/dev/null; then
    success "instaloader found."
else
    warn "instaloader not found. Needed only for downloading Instagram saved posts."
    echo "  Install:"
    echo "    pip install instaloader"
    echo ""
fi

# ── Virtual environment ───────────────────────────────────────────────

if [ -d "$PROJECT_DIR/.venv" ]; then
    info "Virtual environment already exists at .venv"
else
    info "Creating virtual environment at .venv..."
    python3 -m venv "$PROJECT_DIR/.venv"
    success "Virtual environment created."
fi

# ── Activate & install ────────────────────────────────────────────────

source "$PROJECT_DIR/.venv/bin/activate"
info "Installing framemine in editable mode..."
pip install -e . --quiet
success "framemine installed."

# ── Done ──────────────────────────────────────────────────────────────

echo ""
success "Setup complete!"
echo ""
info "Next steps:"
echo "  1. Activate the environment:"
echo "       source .venv/bin/activate"
echo ""
echo "  2. Set your Gemini API key:"
echo "       export GEMINI_API_KEY=\"your-key-here\""
echo ""
echo "  3. Copy the example config:"
echo "       cp config.example.yaml framemine.yaml"
echo ""
echo "  4. Verify everything works:"
echo "       framemine check"
echo ""
echo "  5. See available schemas:"
echo "       framemine schemas"
echo ""
echo "  6. Start extracting:"
echo "       framemine extract ./my_reels/ -s books -o my_books"
echo ""
