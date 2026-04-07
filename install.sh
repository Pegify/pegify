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
    fail "Binary downloaded but won't run. This may be an architecture mismatch."
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

providers:
  anthropic:
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

# ── Step 5: API key setup ──
ANTHROPIC_KEY="${ANTHROPIC_API_KEY:-}"
if [ -z "$ANTHROPIC_KEY" ] && grep -q "api_key: ''" "$PEGIFY_CONFIG" 2>/dev/null; then
    echo ""
    info "No ANTHROPIC_API_KEY found in environment."
    read -rp "  Enter your Anthropic API key (or press Enter to skip): " ANTHROPIC_KEY
    if [ -n "$ANTHROPIC_KEY" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/api_key: ''/api_key: '$ANTHROPIC_KEY'/" "$PEGIFY_CONFIG"
        else
            sed -i "s/api_key: ''/api_key: '$ANTHROPIC_KEY'/" "$PEGIFY_CONFIG"
        fi
        ok "API key configured"
    else
        warn "No API key set. Add it later: ~/.pegify/config.yaml"
    fi
fi

# ── Step 6: Install Claude Code plugin ──
info "Checking Claude Code..."
if command -v claude &>/dev/null; then
    ok "Claude Code CLI found"
    info "Installing Pegify plugin for Claude Code..."
    claude plugins install github:Pegify/pegify 2>/dev/null && ok "Plugin installed" || warn "Plugin install failed — run manually: claude plugins install github:Pegify/pegify"
else
    warn "Claude Code not found. Install it: npm i -g @anthropic-ai/claude-code"
    warn "Then run: claude plugins install github:Pegify/pegify"
fi

# ── Step 7: Start daemon ──
info "Starting Pegify daemon..."
if curl -s http://127.0.0.1:7654/health &>/dev/null; then
    ok "Daemon already running"
else
    "${INSTALL_DIR}/pegify" daemon start &>/dev/null &
    sleep 2
    if curl -s http://127.0.0.1:7654/health &>/dev/null; then
        ok "Daemon started (PID $!)"
    else
        warn "Daemon didn't start automatically. Run: pegify daemon start"
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
