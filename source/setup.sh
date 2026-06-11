#!/usr/bin/env bash
#
# setup.sh — idempotent bootstrap for a local PequeRoku checkout.
#
# Performs only safe, local actions so re-running is always fine:
#   - create source/.env, web_service/.env, vm_service/.env from their templates
#     when missing, generating random secrets and keeping shared values in sync;
#   - on a Linux host with /dev/kvm, write docker-compose.override.yaml so the VM
#     service gets KVM (fast boots). On macOS nothing is written.
#
# Never overwrites an existing file. Next step after running: `docker compose up -d`.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

c_ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
c_skip() { printf '  \033[1;34m•\033[0m %s\n' "$*"; }
c_warn() { printf '  \033[1;33m!\033[0m %s\n' "$*" >&2; }

CREATED=()
SKIPPED=()

# --------------------------------------------------------------------------- #
# Small .env helpers (portable across macOS bash 3.2 and Linux)
# --------------------------------------------------------------------------- #
gen_hex() {
  # $1 = number of bytes; prints lowercase hex with no newline noise
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    head -c "$1" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

read_env_var() {
  # read_env_var FILE KEY -> value of last `KEY=` line, empty if absent
  local file="$1" key="$2"
  [ -f "$file" ] || return 0
  grep -E "^${key}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

set_env_var() {
  # set_env_var FILE KEY VALUE -> replace the KEY= line in FILE, or append it
  local file="$1" key="$2" value="$3" tmp found=0
  tmp="$(mktemp)"
  if [ -f "$file" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      case "$line" in
        "${key}="*) printf '%s=%s\n' "$key" "$value"; found=1 ;;
        *)          printf '%s\n' "$line" ;;
      esac
    done < "$file" > "$tmp"
  fi
  [ "$found" -eq 1 ] || printf '%s=%s\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$file"
}

# --------------------------------------------------------------------------- #
# Resolve shared secrets once. Adopt whatever already exists on disk; only fill
# missing values. setup.sh never rotates existing secrets.
#
# DB_PASSWORD is deliberately NOT randomized: Postgres only applies a password on
# the FIRST init of its data volume, so a random one silently breaks every time
# the volume (.db_data / named volume) outlives .env — a fresh clone, a reset, a
# re-run — with "password authentication failed". A stable default keeps the DB
# reachable across all of those. The DB isn't published outside the compose
# network; set a custom DB_PASSWORD explicitly if you need one (then you own the
# volume lifecycle). SECRET_KEY stays random — changing it is harmless.
# --------------------------------------------------------------------------- #
DB_PASSWORD="$(read_env_var .env DB_PASSWORD)"
[ -n "$DB_PASSWORD" ] || DB_PASSWORD="$(read_env_var web_service/.env DB_PASSWORD)"
[ -n "$DB_PASSWORD" ] || DB_PASSWORD="mypassword"

SECRET_KEY="$(read_env_var web_service/.env SECRET_KEY)"
[ -n "$SECRET_KEY" ] || SECRET_KEY="$(read_env_var .env SECRET_KEY)"
[ -n "$SECRET_KEY" ] || SECRET_KEY="$(gen_hex 32)"

DB_NAME="$(read_env_var .env DB_NAME)"
[ -n "$DB_NAME" ] || DB_NAME="$(read_env_var web_service/.env DB_NAME)"
[ -n "$DB_NAME" ] || DB_NAME="mydb"

DB_USER="$(read_env_var .env DB_USER)"
[ -n "$DB_USER" ] || DB_USER="$(read_env_var web_service/.env DB_USER)"
[ -n "$DB_USER" ] || DB_USER="myuser"

# --------------------------------------------------------------------------- #
# Create env files from templates when missing
# --------------------------------------------------------------------------- #
echo "Environment files:"

if [ -f .env ]; then
  c_skip ".env (exists, left untouched)"; SKIPPED+=(".env")
else
  cp .env.template .env
  set_env_var .env DB_NAME "$DB_NAME"
  set_env_var .env DB_USER "$DB_USER"
  set_env_var .env DB_PASSWORD "$DB_PASSWORD"
  set_env_var .env SECRET_KEY "$SECRET_KEY"
  c_ok ".env (created; secrets generated or adopted from existing config)"; CREATED+=(".env")
fi

if [ -f web_service/.env ]; then
  c_skip "web_service/.env (exists, left untouched)"; SKIPPED+=("web_service/.env")
else
  cp web_service/.env.template web_service/.env
  # Keep the values the web container reads in sync with .env / the db service.
  set_env_var web_service/.env SECRET_KEY "$SECRET_KEY"
  set_env_var web_service/.env DB_NAME "$DB_NAME"
  set_env_var web_service/.env DB_USER "$DB_USER"
  set_env_var web_service/.env DB_PASSWORD "$DB_PASSWORD"
  c_ok "web_service/.env (created, synced with .env)"; CREATED+=("web_service/.env")
fi

if [ -f vm_service/.env ]; then
  c_skip "vm_service/.env (exists, left untouched)"; SKIPPED+=("vm_service/.env")
else
  cp vm_service/.env.template vm_service/.env
  c_ok "vm_service/.env (created from template)"; CREATED+=("vm_service/.env")
fi

# --------------------------------------------------------------------------- #
# KVM compose override (Linux + /dev/kvm only) — Change 6
# --------------------------------------------------------------------------- #
echo "KVM override:"
if [ "$(uname -s)" = "Linux" ] && [ -e /dev/kvm ]; then
  if [ -f docker-compose.override.yaml ]; then
    c_skip "docker-compose.override.yaml (exists, left untouched)"
    SKIPPED+=("docker-compose.override.yaml")
  else
    cat > docker-compose.override.yaml <<'YAML'
# Generated by setup.sh on a Linux host with /dev/kvm. Machine-local (gitignored).
# Gives the VM service KVM acceleration for fast boots. Not written on macOS.
services:
  vm_services:
    devices:
      - /dev/kvm:/dev/kvm
    security_opt:
      - seccomp=unconfined
YAML
    c_ok "docker-compose.override.yaml (KVM passthrough enabled)"
    CREATED+=("docker-compose.override.yaml")
  fi
elif [ "$(uname -s)" = "Linux" ]; then
  c_warn "Linux host but /dev/kvm is missing — VMs would run under SLOW emulation."
  c_warn "  Check:  ls -l /dev/kvm  |  lsmod | grep kvm  |  egrep -c '(vmx|svm)' /proc/cpuinfo"
  c_warn "  Fixes:  enable virtualization (VT-x/AMD-V) in BIOS; load the module"
  c_warn "          (sudo modprobe kvm_intel  OR  kvm_amd); then re-run ./setup.sh."
  c_warn "  Note: Docker DESKTOP on Linux runs containers in its own VM, so /dev/kvm"
  c_warn "        passthrough needs the native Docker Engine (docker-ce), not Desktop."
else
  c_skip "macOS host — no /dev/kvm; the dockerized VM service runs under emulation."
fi

# --------------------------------------------------------------------------- #
# Warnings
# --------------------------------------------------------------------------- #
if [ -d .db_data ]; then
  echo "Warnings:"
  c_warn "Existing Postgres data found (.db_data). It keeps the password from its"
  c_warn "  first init, ignoring .env. If login/migrate fails with 'password"
  c_warn "  authentication failed', reset the DB:"
  c_warn "    docker compose down -v && sudo rm -rf .db_data .redis_data && ./start.sh"
fi

# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
echo
echo "Summary:"
[ "${#CREATED[@]}" -gt 0 ] && echo "  created: ${CREATED[*]}"
[ "${#SKIPPED[@]}" -gt 0 ] && echo "  skipped: ${SKIPPED[*]}"
echo
echo "Next: docker compose up -d"
