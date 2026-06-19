#!/usr/bin/env bash
#
# start.sh — one command to bring PequeRoku up from a fresh checkout.
#
# Idempotent: runs the local bootstrap (setup.sh) and then `docker compose up`.
# Re-running is always safe — setup.sh never overwrites existing files and
# compose only recreates containers whose config changed.
#
# Usage:
#   ./start.sh                 # setup + build + up -d
#   ./start.sh --no-build      # skip image rebuild (faster when nothing changed)
#   ./start.sh <svc> [svc...]  # extra args are forwarded to `docker compose up`
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

err() { printf '\033[1;31m[start] %s\033[0m\n' "$*" >&2; }
log() { printf '\033[1;34m[start]\033[0m %s\n' "$*"; }

# Useful post-launch commands. Printed BOTH up front (before the noisy build) and
# again at the end so it survives the `compose up` output scrolling it away.
# Uses ${COMPOSE[*]} so it reflects sudo / the resolved compose flavor verbatim.
print_useful_commands() {
  # If you launched this as root (e.g. `sudo ./start.sh` because Docker needs root
  # here), the same commands need sudo from your normal shell — show them with it.
  # Display only: it NEVER changes how we invoke compose.
  local sudo=""
  [ "$(id -u)" -eq 0 ] && sudo="sudo "
  echo "  ${sudo}${COMPOSE[*]} ps           # service status"
  echo "  ${sudo}${COMPOSE[*]} logs -f      # follow logs"
  echo "  Dashboard: http://localhost/dashboard/"
}

# --------------------------------------------------------------------------- #
# Resolve the compose command (plugin `docker compose` or legacy binary)
# --------------------------------------------------------------------------- #
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  err "Docker Compose not found. Install Docker Desktop or the compose plugin."
  exit 1
fi

if command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
  err "Docker daemon is not reachable. Start Docker (or run with sudo) and re-run ./start.sh"
  exit 1
fi

# --------------------------------------------------------------------------- #
# Parse our own flags; everything else is forwarded to `compose up`
# --------------------------------------------------------------------------- #
BUILD=1
PASSTHRU=()
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    *)          PASSTHRU+=("$arg") ;;
  esac
done

# Show the cheat-sheet up front (it'll be repeated at the end — the build output
# in between tends to scroll the final copy off-screen).
echo
log "Useful commands (shown again when it's up):"
print_useful_commands
echo

# --------------------------------------------------------------------------- #
# 1) Idempotent bootstrap (env files + KVM override)
# --------------------------------------------------------------------------- #
log "Bootstrapping local config..."
bash ./setup.sh

# --------------------------------------------------------------------------- #
# 1.5) Keep each Poetry lockfile in sync with its pyproject (auto-relock)
#
# `poetry install` in the image build ABORTS when pyproject.toml has drifted from
# poetry.lock ("changed significantly since poetry.lock was last generated"), so
# a forgotten `poetry lock` after editing dependencies breaks the build. Refresh
# stale lockfiles here (host-side, where Poetry lives). `--no-update` only rewrites
# the hash / adds already-resolvable deps; it NEVER bumps pinned versions, so the
# build stays reproducible. Only services that already track a poetry.lock are
# touched (we never create one where there wasn't).
# --------------------------------------------------------------------------- #
sync_poetry_locks() {
  if ! command -v poetry >/dev/null 2>&1; then
    log "Poetry not on host; skipping lockfile sync (image build will fail loudly if a lock is stale)."
    return 0
  fi
  local svc
  for svc in web_service vm_service mcp_service; do
    [ -f "$svc/pyproject.toml" ] && [ -f "$svc/poetry.lock" ] || continue
    if ! (cd "$svc" && poetry check --lock >/dev/null 2>&1); then
      log "  $svc: poetry.lock is stale -> relocking (no version bump)..."
      if ! (cd "$svc" && poetry lock --no-update --no-interaction --no-ansi >/dev/null 2>&1); then
        err "Failed to relock $svc. Fix pyproject.toml or run 'cd source/$svc && poetry lock'."
        exit 1
      fi
    fi
  done
}

if [ "$BUILD" -eq 1 ]; then
  log "Syncing Poetry lockfiles..."
  sync_poetry_locks
fi

# --------------------------------------------------------------------------- #
# 2) Bring the stack up
# --------------------------------------------------------------------------- #
UP=(up -d)
[ "$BUILD" -eq 1 ] && UP+=(--build)
[ "${#PASSTHRU[@]}" -gt 0 ] && UP+=("${PASSTHRU[@]}")

echo
log "Running: ${COMPOSE[*]} ${UP[*]}"
if ! "${COMPOSE[@]}" "${UP[@]}"; then
  err "compose up failed — see the build/run output above."
  exit 1
fi

echo
log "Stack is up. Useful commands:"
print_useful_commands
