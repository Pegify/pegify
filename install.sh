#!/usr/bin/env bash
# Pegify end-user installer. Binary mode only, no source clone required.
set -euo pipefail

GITHUB_REPO="Pegify/pegify"
PEGIFY_HOME="$HOME/.pegify"
PEGIFY_CONFIG="$PEGIFY_HOME/config.yaml"
INSTALL_DIR="$HOME/.local/bin"
NO_SERVICE=false
TARGET_VERSION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-service) NO_SERVICE=true; shift ;;
    --version)    TARGET_VERSION="$2"; shift 2 ;;
    --help|-h)
      cat <<'HELP'
Pegify Installer

USAGE
  bash install.sh [OPTIONS]

MODES
  --binary (default) Download a pre-built native binary from GitHub Releases.

OPTIONS
  --no-service      Skip daemon service installation (useful in CI/containers)
  --version X.Y     Binary mode: pin to a specific release version
  --help            Show this help
HELP
      exit 0
      ;;
    *) shift ;;
  esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[pegify]${NC} $*"; }
ok()    { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
fail()  { echo -e "${RED}[ FAIL ]${NC} $*"; exit 1; }

echo ""
echo -e "${BOLD}${CYAN}  Pegify End-User Installer${NC}"
echo ""

OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
  Linux)  PLATFORM="linux" ;;
  Darwin) PLATFORM="macos" ;;
  *)      fail "Unsupported OS: $OS. Pegify supports Linux and macOS." ;;
esac

case "$ARCH" in
  x86_64|amd64)  ARCH="x86_64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *)             fail "Unsupported architecture: $ARCH. Pegify supports x86_64 and arm64." ;;
esac

BINARY_NAME="pegify-${PLATFORM}-${ARCH}"
info "Platform: ${PLATFORM}/${ARCH}"

if [ -n "$TARGET_VERSION" ]; then
  VERSION="$TARGET_VERSION"
else
  info "Checking latest version..."
  RELEASE_JSON=$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" 2>/dev/null) \
    || fail "Cannot reach GitHub. Check your internet connection."
  VERSION=$(echo "$RELEASE_JSON" | grep '"tag_name"' | head -1 | sed 's/.*"v\([^"]*\)".*/\1/')
fi

[ -z "$VERSION" ] && fail "Could not determine latest Pegify version."
info "Version: ${VERSION}"

DOWNLOAD_BASE="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}"
DOWNLOAD_URL="${DOWNLOAD_BASE}/${BINARY_NAME}"
CHECKSUMS_URL="${DOWNLOAD_BASE}/checksums.txt"

mkdir -p "$PEGIFY_HOME"
mkdir -p "$INSTALL_DIR"
TARGET="${INSTALL_DIR}/pegify"

if [ -n "$TARGET_VERSION" ]; then
  DOWNLOAD_URL="${DOWNLOAD_BASE}/${BINARY_NAME}"
fi

info "Downloading Pegify v${VERSION}..."
if [ -t 1 ]; then
  curl -fL --progress-bar -o "$TARGET" "$DOWNLOAD_URL"
else
  curl -fsSL -o "$TARGET" "$DOWNLOAD_URL"
fi

[ -s "$TARGET" ] || fail "Downloaded binary is empty."

chmod 0600 "$PEGIFY_CONFIG" 2>/dev/null || true
chmod +x "$TARGET"
chmod 0700 "$PEGIFY_HOME"

info "Verifying checksum..."
CHECKSUMS=$(curl -fsSL "$CHECKSUMS_URL" 2>/dev/null) || true
if [ -n "$CHECKSUMS" ]; then
  EXPECTED=$(echo "$CHECKSUMS" | grep "$BINARY_NAME" | awk '{print $1}')
  if [ -n "$EXPECTED" ]; then
    if command -v sha256sum &>/dev/null; then
      ACTUAL=$(sha256sum "$TARGET" | awk '{print $1}')
    elif command -v shasum &>/dev/null; then
      ACTUAL=$(shasum -a 256 "$TARGET" | awk '{print $1}')
    else
      warn "sha256sum or shasum not found. Skipping checksum verification."
    fi
    if [ -n "${ACTUAL:-}" ]; then
      if [ "$ACTUAL" != "$EXPECTED" ]; then
        rm -f "$TARGET"
        fail "Checksum mismatch. Expected: ${EXPECTED} Got: ${ACTUAL}"
      fi
      ok "Checksum verified."
    fi
  else
    warn "Checksum entry for ${BINARY_NAME} not found. Skipping verification."
  fi
else
  warn "Could not download checksums. Skipping verification."
fi

if [ "$PLATFORM" = "macos" ]; then
  xattr -d com.apple.quarantine "$TARGET" 2>/dev/null || true
fi

if "$TARGET" --version &>/dev/null; then
  ok "Pegify ${VERSION} is ready."
else
  rm -f "$TARGET"
  fail "Downloaded binary will not run. Architecture mismatch? Run: file ${TARGET}"
fi

if ! echo "$PATH" | tr ':' '\n' | grep -qx "$INSTALL_DIR"; then
  SHELL_RC="$HOME/.profile"
  case "${SHELL:-/bin/bash}" in
    */zsh)  SHELL_RC="$HOME/.zshrc" ;;
    */bash) SHELL_RC="$HOME/.bashrc" ;;
    *)      SHELL_RC="$HOME/.profile" ;;
  esac
  echo "export PATH=\"$INSTALL_DIR:\$PATH\"" >> "$SHELL_RC"
  info "Added ${INSTALL_DIR} to PATH in ${SHELL_RC}."
fi

if [ "$NO_SERVICE" != "true" ]; then
  info "Installing daemon service..."
  if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable pegify.service 2>/dev/null || true
  elif [ "$PLATFORM" = "macos" ]; then
    launchctl unload "$PEGIFY_HOME/launchd/pegify.plist" 2>/dev/null || true
    launchctl load "$PEGIFY_HOME/launchd/pegify.plist" 2>/dev/null || true
  fi
fi

echo ""
echo -e "${GREEN}  Pegify v${VERSION} installed successfully.${NC}"
echo ""
echo -e "  Binary:     ${BOLD}${TARGET}${NC}"
echo -e "  Config:     ${BOLD}${PEGIFY_CONFIG}${NC}"
echo -e "  Docs:       ${BOLD}https://pegify.dev${NC}"
echo ""
