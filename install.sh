#!/usr/bin/env bash
# Pegify installer — downloads and sets up Pegify on any machine.
# Usage: curl -fsSL https://raw.githubusercontent.com/Pegify/pegify/main/install.sh | bash

set -euo pipefail

VERSION="0.1.0"
PEGIFY_HOME="$HOME/.pegify"
PEGIFY_CONFIG="$PEGIFY_HOME/config.yaml"
INSTALL_DIR="$HOME/.local/bin"
GITHUB_REPO="Pegify/pegify"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[pegify]${NC} $*"; }
ok()    { echo -e "${GREEN}[  OK  ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[ WARN ]${NC} $*"; }
fail()  { echo -e "${RED}[ FAIL ]${NC} $*"; exit 1; }

echo ""
echo -e "${CYAN}  ____            _  __       ${NC}"
echo -e "${CYAN} |  _ \\ ___  __ _(_)/ _|_   _ ${NC}"
echo -e "${CYAN} | |_) / _ \\/ _\` | | |_| | | |${NC}"
echo -e "${CYAN} |  __/  __/ (_| | |  _| |_| |${NC}"
echo -e "${CYAN} |_|   \\___|\\__, |_|_|  \\__, |${NC}"
echo -e "${CYAN}            |___/       |___/ ${NC}"
echo ""
echo -e "  Agent Operations Platform — v${VERSION}"
echo ""

# ── Detect OS/Arch ──
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
    *)             fail "Unsupported architecture: $ARCH" ;;
esac

BINARY_NAME="pegify-${PLATFORM}-${ARCH}"
DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}/${BINARY_NAME}"

info "Platform: ${PLATFORM}/${ARCH}"

# ── Step 1: Download Pegify binary ──
info "Downloading Pegify v${VERSION}..."
mkdir -p "$INSTALL_DIR"

if command -v curl &>/dev/null; then
    HTTP_CODE=$(curl -fsSL -w "%{http_code}" -o "${INSTALL_DIR}/pegify" "$DOWNLOAD_URL" 2>/dev/null) || true
    if [ "$HTTP_CODE" != "200" ] && [ ! -s "${INSTALL_DIR}/pegify" ]; then
        rm -f "${INSTALL_DIR}/pegify"
        fail "Download failed (HTTP $HTTP_CODE). Check https://github.com/${GITHUB_REPO}/releases for available binaries."
    fi
elif command -v wget &>/dev/null; then
    wget -q -O "${INSTALL_DIR}/pegify" "$DOWNLOAD_URL" || fail "Download failed. Check https://github.com/${GITHUB_REPO}/releases"
else
    fail "Neither curl nor wget found. Install one and retry."
fi

chmod +x "${INSTALL_DIR}/pegify"

# macOS: clear quarantine and re-sign locally so Gatekeeper allows it
if [ "$PLATFORM" = "macos" ]; then
    xattr -cr "${INSTALL_DIR}/pegify" 2>/dev/null || true
    codesign --force --deep --sign - "${INSTALL_DIR}/pegify" 2>/dev/null || true
fi

ok "Downloaded to ${INSTALL_DIR}/pegify"

# ── Step 2: Ensure ~/.local/bin is in PATH ──
if ! echo "$PATH" | tr ':' '\n' | grep -q "$INSTALL_DIR"; then
    SHELL_RC=""
    case "$SHELL" in
        */zsh)  SHELL_RC="$HOME/.zshrc" ;;
        */bash) SHELL_RC="$HOME/.bashrc" ;;
        *)      SHELL_RC="$HOME/.profile" ;;
    esac
    if [ -n "$SHELL_RC" ] && ! grep -q "$INSTALL_DIR" "$SHELL_RC" 2>/dev/null; then
        echo "export PATH=\"${INSTALL_DIR}:\$PATH\"" >> "$SHELL_RC"
        ok "Added ${INSTALL_DIR} to PATH in ${SHELL_RC}"
    fi
    export PATH="${INSTALL_DIR}:$PATH"
fi

# ── Step 3: Verify binary works ──
if "${INSTALL_DIR}/pegify" --version &>/dev/null; then
    ok "Pegify $(${INSTALL_DIR}/pegify --version 2>&1)"
else
    if [ "$PLATFORM" = "macos" ]; then
        fail "Binary won't run. Try manually: codesign --force --deep --sign - ${INSTALL_DIR}/pegify && ${INSTALL_DIR}/pegify --version"
    else
        fail "Binary downloaded but won't run. This may be an architecture mismatch."
    fi
fi

# ── Step 4: Initialize ~/.pegify ──
info "Setting up ~/.pegify..."
mkdir -p "$PEGIFY_HOME"

if [ ! -f "$PEGIFY_CONFIG" ]; then
    cat > "$PEGIFY_CONFIG" << 'YAML'
# Pegify configuration
daemon:
  host: 127.0.0.1
  port: 7654
  auto_restart: true

# Auth mode: "subscription" uses your Claude Code login (no API key needed).
# Set to "api_key" and add providers.anthropic.api_key for direct API access.
auth_mode: subscription

providers:
  anthropic:
    # Only needed if auth_mode is "api_key" (pay-per-token from console.anthropic.com).
    # If you use Claude Code with a subscription plan (Pro/Max), leave this empty —
    # agents run through Claude Code which uses your subscription.
    api_key: ''
    models:
      - id: claude-sonnet-4-6
        name: Claude Sonnet 4.6
        context_window: 200000
        max_tokens: 64000
      - id: claude-opus-4-6
        name: Claude Opus 4.6
        context_window: 1000000
        max_tokens: 64000
      - id: claude-haiku-4-5
        name: Claude Haiku 4.5
        context_window: 200000
        max_tokens: 8192

approval:
  mode: smart

channels:
  - name: dev
    description: Development channel

agents: []
YAML
    ok "Created config at $PEGIFY_CONFIG"
else
    ok "Config already exists"
fi

# ── Step 6: Install Claude Code plugin ──
info "Checking Claude Code..."
if command -v claude &>/dev/null; then
    ok "Claude Code CLI found"
    info "Adding Pegify marketplace..."
    claude mcp add-marketplace pegify https://marketplace.pegify.io 2>/dev/null || true
    info "Installing Pegify plugin for Claude Code..."
    claude plugins install github:Pegify/pegify 2>/dev/null && ok "Plugin installed" || warn "Plugin install failed — run manually: claude plugins install github:Pegify/pegify"
else
    warn "Claude Code not found. Install it: npm i -g @anthropic-ai/claude-code"
    warn "Then run: claude plugins install github:Pegify/pegify"
fi

# ── Step 6b: Install code-review-graph (core tooling) ──
info "Checking code-review-graph..."
if command -v code-review-graph &>/dev/null; then
    ok "code-review-graph already installed"
else
    info "Installing code-review-graph..."
    pip install code-review-graph 2>/dev/null && ok "code-review-graph installed" || \
    pip3 install code-review-graph 2>/dev/null && ok "code-review-graph installed" || \
    warn "code-review-graph install failed — run manually: pip install code-review-graph"
fi

# ── Step 7: Install & start daemon service ──
info "Installing Pegify daemon service..."
"${INSTALL_DIR}/pegify" daemon install 2>/dev/null && ok "Daemon service installed" || warn "Service install failed — run manually: pegify daemon install"

info "Starting Pegify daemon..."
if curl -s http://127.0.0.1:7654/health &>/dev/null; then
    ok "Daemon already running"
else
    # Service should auto-start from install, but check
    sleep 2
    if curl -s http://127.0.0.1:7654/health &>/dev/null; then
        ok "Daemon started via service"
    else
        # Fallback: direct start
        "${INSTALL_DIR}/pegify" daemon start &>/dev/null &
        sleep 2
        if curl -s http://127.0.0.1:7654/health &>/dev/null; then
            ok "Daemon started (PID $!)"
        else
            warn "Daemon didn't start automatically. Run: pegify daemon start"
        fi
    fi
fi

# ── Step 8: Health check ──
echo ""
info "Running health check..."
echo ""
"${INSTALL_DIR}/pegify" doctor 2>/dev/null || true

# ── Done ──
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Pegify v${VERSION} is ready!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Quick start:"
echo "    pegify init                          # Initialize a project"
echo "    pegify agent create Nova --role dev  # Create an agent"
echo "    pegify say dev \"Hello team!\"         # Send a message"
echo "    pegify doctor                        # Check health"
echo ""
echo "  Claude Code plugin:"
echo "    claude plugins install github:Pegify/pegify"
echo ""
echo "  Docs: https://github.com/${GITHUB_REPO}"
echo ""
if ! echo "$PATH" | tr ':' '\n' | grep -q "$INSTALL_DIR"; then
    echo -e "  ${YELLOW}NOTE: Restart your terminal or run: source ~/.bashrc${NC}"
    echo ""
fi
