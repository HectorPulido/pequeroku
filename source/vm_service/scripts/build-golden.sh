#!/usr/bin/env bash
#
# build-golden.sh — Build a pre-baked "golden" VM image for pequeroku.
#
# Downloads the matching Debian/Ubuntu cloud base image and bakes everything
# cloud-init would otherwise do at runtime directly into the image:
#   - the SSH user (+ root) with the service public key in authorized_keys
#   - the sshd drop-in config (PermitRootLogin yes, no password auth, UseDNS no)
#   - DHCP networking via systemd-networkd (with pinned public DNS resolvers)
#   - automatic root filesystem growth (self-contained oneshot unit)
#   - pre-generated SSH host keys
#   - a curated, headless dev baseline: git, curl, build toolchain, docker,
#     cloudflared, fastfetch, ... (see BASE_PACKAGES) plus any --packages extras
# ...then DISABLES cloud-init so runtime boots skip the ~40s pipeline and SSH is
# ready in ~10s. Pair with a golden *.meta.json (auto-written) or VM_USE_CLOUD_INIT=false.
#
# HEADLESS / ZERO-DEPENDENCY BY DEFAULT
# ------------------------------------
# You do NOT need qemu or libguestfs installed on the host. When the host lacks
# `virt-customize`, the script spins up a throwaway Docker "builder" container
# that already has libguestfs + qemu, mounts vm_data, and bakes the image there
# with the fast `virt-customize` path (no full VM boot). This is the macOS path.
# Only Docker is required. Override with --docker / --no-docker.
#
# SSH KEY — taken from vm_data, generated if missing
# --------------------------------------------------
# By default the public key is resolved from (first match wins):
#   1. --pubkey <path>                       (explicit)
#   2. $VM_SSH_PRIVKEY.pub                    (if it exists)
#   3. <repo>/vm_data/keys/id_vm_pequeroku.pub  (canonical — same as entrypoint.sh)
#   4. ~/.ssh/id_vm_pequeroku.pub
# If NONE exist, an ed25519 keypair is generated into vm_data/keys/ (exactly like
# vm_service/entrypoint.sh does) so a clean checkout works with zero key setup.
#
# Bake methods:
#   * virt-customize (libguestfs) — fast, no full boot. Used on the host when
#     available, otherwise inside the Docker builder container. (Default.)
#   * boot — boots the image once under host QEMU with a one-shot cloud-init that
#     bakes + powers off, then installs packages over SSH. Native fallback only.
#
# Usage:
#   scripts/build-golden.sh [options]
#
# Options:
#   --distro    <debian12|ubuntu2204>   Guest distro (default: debian12)
#   --arch      <auto|amd64|arm64>      Guest arch (default: auto = host arch)
#   --out       <path>                  Output qcow2 (default: vm_data/base/<distro>-golden.qcow2)
#   --user      <name>                  SSH user to bake (default: $VM_SSH_USER or root)
#   --pubkey    <path>                  Public key to inject (default: auto-resolve, see above)
#   --size      <GiB>                   Resize image to this size (default: 10)
#   --packages  <csv>                   Extra apt packages on top of the baseline
#   --no-base-packages                  Skip the curated dev baseline (minimal bake)
#   --no-cloudflared                    Do not install cloudflared
#   --no-fastfetch                      Do not install fastfetch (GitHub release .deb)
#   --apt-upgrade                       Run apt update + full-upgrade on the baked image
#   --privkey   <path>                  Private key for the boot-method SSH pass (default: PUBKEY without .pub)
#   --docker                            Force the dockerized virt-customize bake
#   --no-docker                         Never use Docker (bake natively; needs host qemu/libguestfs)
#   --builder-image <name>              Builder image tag (default: pequeroku-golden-builder)
#   --rebuild-builder                   Rebuild the Docker builder image even if cached
#   --method    <auto|virt-customize|boot>  Native bake method when not using Docker (default: auto)
#   --boot-timeout <secs>               Max wait for the boot/upgrade bake VM (default: 900)
#   --cache     <dir>                   Where to cache downloaded base images (default: vm_data/base/.cache)
#   --force                             Rebuild even if --out already exists
#   --clobber-base                      Allow overwriting a base that live VM overlays back onto (CORRUPTS them)
#   --write-meta-only                   Only (re)write <out>.meta.json for an existing image, then exit
#   -v | --verbose                      Trace every step (set -x + verbose qemu/libguestfs) to locate a hang
#   -h | --help                         Show this help
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Paths / defaults
# --------------------------------------------------------------------------- #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="${SCRIPT_DIR}/$(basename "${BASH_SOURCE[0]}")"
VM_SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
# <source> dir holds both vm_service/ and vm_data/. Mounted whole into the builder
# container at the SAME absolute path, so every default path resolves identically
# inside and out — no host<->container path translation needed.
SOURCE_DIR="$(cd "${VM_SERVICE_DIR}/.." && pwd)"
VM_DATA_DIR="${SOURCE_DIR}/vm_data"
DEFAULT_BASE_DIR="${VM_DATA_DIR}/base"
DEFAULT_KEYS_DIR="${VM_DATA_DIR}/keys"

DISTRO="debian12"
ARCH="auto"
OUT=""
SSH_USER="${VM_SSH_USER:-root}"
PUBKEY=""                # empty -> resolve_pubkey() picks/generates one
PUBKEY_EXPLICIT="0"      # set by --pubkey: an explicit key must exist (no fallback)
PRIVKEY=""               # private key for the boot-method SSH pass (default: PUBKEY without .pub)
SIZE_GIB="10"
PACKAGES=""              # extra apt packages, ON TOP of BASE_PACKAGES below

# Curated, headless dev baseline baked into every golden. Goal: a cloned repo
# configures + builds on the first try, and the box is comfortable to live in over
# SSH — with NO desktop/GUI packages. Three things are installed separately by
# emit_provision_script because they need more than a plain apt package: cloudflared
# (its own apt repo), fastfetch (GitHub .deb — not in Debian 12), and the Docker
# Compose v2 plugin (GitHub binary, so `docker compose` works alongside the v1
# `docker-compose` that lives in this list). Installed unless --no-base-packages.
BASE_PACKAGES="ca-certificates,curl,wget,gnupg,git,python3-venv,python3-pip,python3-dev,build-essential,openssh-client,vim,nano,less,htop,tmux,unzip,zip,jq,rsync,sudo,iproute2,dnsutils,docker.io,docker-compose"
NO_BASE_PACKAGES="0"     # set by --no-base-packages to restore a minimal bake
INSTALL_CLOUDFLARED="1"  # cleared by --no-cloudflared
INSTALL_FASTFETCH="1"    # cleared by --no-fastfetch (installed from GitHub .deb)
APT_UPGRADE="0"          # run apt update + full-upgrade on the baked image
METHOD="auto"            # native bake method (when not dockerized)
CACHE_DIR=""
FORCE="0"
CLOBBER_BASE="0"
WRITE_META_ONLY="0"
BOOT_TIMEOUT="900"

USE_DOCKER="auto"        # auto|0|1 — whether to bake inside the Docker builder
IN_CONTAINER="0"         # internal: set by --__in-container after the docker re-exec
BUILDER_IMAGE="pequeroku-golden-builder"
REBUILD_BUILDER="0"
VERBOSE="0"              # --verbose/-v: set -x trace + verbose qemu/libguestfs/curl

ORIG_ARGS=("$@")         # captured verbatim to forward into the builder container

log()  { printf '\033[1;34m[build-golden]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[build-golden] WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[build-golden] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '/^# Usage:/,/^#   -h /p' "${SCRIPT_PATH}" | sed 's/^# \{0,1\}//'
  exit 0
}

# Expand a leading ~ to $HOME (cloud env files store VM_SSH_PRIVKEY=~/.ssh/...).
expand_tilde() {
  case "$1" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s' "${HOME}/${1#\~/}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# Write a sidecar <image>.meta.json describing the golden so vm_service can
# auto-detect that cloud-init must be skipped for it (see settings.py resolution).
write_meta() {
  local img="$1"
  local meta="${img}.meta.json"
  local built_at; built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  cat > "$meta" <<EOF
{
  "golden": true,
  "distro": "${DISTRO}",
  "arch": "${ARCH}",
  "ssh_user": "${SSH_USER}",
  "built_at": "${built_at}",
  "builder": "build-golden.sh"
}
EOF
  log "Wrote golden metadata: ${meta}"
}

# --------------------------------------------------------------------------- #
# Parse args
# --------------------------------------------------------------------------- #
while [[ $# -gt 0 ]]; do
  case "$1" in
    --distro)   DISTRO="$2"; shift 2 ;;
    --arch)     ARCH="$2"; shift 2 ;;
    --out)      OUT="$2"; shift 2 ;;
    --user)     SSH_USER="$2"; shift 2 ;;
    --pubkey)   PUBKEY="$2"; PUBKEY_EXPLICIT="1"; shift 2 ;;
    --size)     SIZE_GIB="$2"; shift 2 ;;
    --packages) PACKAGES="$2"; shift 2 ;;
    --no-base-packages) NO_BASE_PACKAGES="1"; shift ;;
    --no-cloudflared)   INSTALL_CLOUDFLARED="0"; shift ;;
    --no-fastfetch)     INSTALL_FASTFETCH="0"; shift ;;
    --apt-upgrade) APT_UPGRADE="1"; shift ;;
    --privkey)  PRIVKEY="$2"; shift 2 ;;
    --docker)    USE_DOCKER="1"; shift ;;
    --no-docker) USE_DOCKER="0"; shift ;;
    --builder-image) BUILDER_IMAGE="$2"; shift 2 ;;
    --rebuild-builder) REBUILD_BUILDER="1"; shift ;;
    --method)   METHOD="$2"; shift 2 ;;
    --boot-timeout) BOOT_TIMEOUT="$2"; shift 2 ;;
    --cache)    CACHE_DIR="$2"; shift 2 ;;
    --force)    FORCE="1"; shift ;;
    --clobber-base) CLOBBER_BASE="1"; shift ;;
    --write-meta-only) WRITE_META_ONLY="1"; shift ;;
    --__in-container) IN_CONTAINER="1"; shift ;;
    -v|--verbose) VERBOSE="1"; shift ;;
    -h|--help)  usage ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# --verbose: trace every command (this script + the one re-exec'd in the container,
# since --verbose rides along in ORIG_ARGS) so a hang shows exactly where it stops.
if [[ "$VERBOSE" == "1" ]]; then
  log "Verbose mode ON (set -x). The last line before a hang is the culprit."
  set -x
fi

# --------------------------------------------------------------------------- #
# Detect host arch + OS
# --------------------------------------------------------------------------- #
HOST_OS="$(uname -s)"      # Linux | Darwin
HOST_MACHINE="$(uname -m)" # x86_64 | aarch64 | arm64

host_arch_to_guest() {
  case "$1" in
    x86_64|amd64)   echo "amd64" ;;
    aarch64|arm64)  echo "arm64" ;;
    *) die "Unsupported host architecture: $1" ;;
  esac
}

if [[ "$ARCH" == "auto" ]]; then
  ARCH="$(host_arch_to_guest "$HOST_MACHINE")"
fi
case "$ARCH" in amd64|arm64) ;; *) die "Invalid --arch: $ARCH (amd64|arm64)";; esac

[[ -n "$CACHE_DIR" ]] || CACHE_DIR="${DEFAULT_BASE_DIR}/.cache"
[[ -n "$OUT" ]]       || OUT="${DEFAULT_BASE_DIR}/${DISTRO}-golden.qcow2"

# --write-meta-only: backfill the sidecar for an already-built golden, then stop.
if [[ "$WRITE_META_ONLY" == "1" ]]; then
  [[ -f "$OUT" ]] || die "Image not found: ${OUT} (nothing to write metadata for; pass --out)"
  write_meta "$OUT"
  exit 0
fi

# --------------------------------------------------------------------------- #
# Resolve the SSH public key (and generate one if nothing exists).
# Precedence: explicit --pubkey > $VM_SSH_PRIVKEY.pub > vm_data/keys > ~/.ssh.
# Mirrors vm_service/entrypoint.sh: the generated key lands in vm_data/keys so
# vm_service reuses the exact same key when it boots VMs.
# --------------------------------------------------------------------------- #
resolve_pubkey() {
  if [[ "$PUBKEY_EXPLICIT" == "1" ]]; then
    [[ -f "$PUBKEY" ]] || die "Public key not found: ${PUBKEY} (passed via --pubkey)"
    log "Using SSH public key (--pubkey): ${PUBKEY}"
    return
  fi

  local cands=()
  if [[ -n "${VM_SSH_PRIVKEY:-}" ]]; then
    local p; p="$(expand_tilde "${VM_SSH_PRIVKEY%.pub}")"
    cands+=("${p}.pub")
  fi
  cands+=("${DEFAULT_KEYS_DIR}/id_vm_pequeroku.pub")
  cands+=("${HOME}/.ssh/id_vm_pequeroku.pub")

  local c
  for c in "${cands[@]}"; do
    if [[ -f "$c" ]]; then
      PUBKEY="$c"
      log "Using existing SSH public key: ${PUBKEY}"
      return
    fi
  done

  # Nothing found — generate an ed25519 keypair into vm_data/keys (same as entrypoint.sh).
  command -v ssh-keygen >/dev/null 2>&1 || die "No SSH key found and ssh-keygen is unavailable to create one"
  local gen="${DEFAULT_KEYS_DIR}/id_vm_pequeroku"
  mkdir -p "$DEFAULT_KEYS_DIR"
  log "No SSH key found; generating ed25519 keypair at ${gen}"
  ssh-keygen -t ed25519 -N "" -C "pequeroku-vm" -f "$gen" >/dev/null
  chmod 600 "$gen"
  PUBKEY="${gen}.pub"
}

resolve_pubkey
[[ -n "$PRIVKEY" ]] || PRIVKEY="${PUBKEY%.pub}"

# Effective package list = curated baseline (unless --no-base-packages) + extras.
EFFECTIVE_PACKAGES="$PACKAGES"
if [[ "$NO_BASE_PACKAGES" != "1" ]]; then
  if [[ -n "$EFFECTIVE_PACKAGES" ]]; then
    EFFECTIVE_PACKAGES="${BASE_PACKAGES},${EFFECTIVE_PACKAGES}"
  else
    EFFECTIVE_PACKAGES="$BASE_PACKAGES"
  fi
fi

log "Host:   ${HOST_OS} / ${HOST_MACHINE}"
log "Target: distro=${DISTRO} arch=${ARCH} size=${SIZE_GIB}GiB"
log "User:   ${SSH_USER}   Pubkey: ${PUBKEY}"
log "Output: ${OUT}"
EXTRAS_DESC=""
[[ "$INSTALL_FASTFETCH"   == "1" ]] && EXTRAS_DESC="${EXTRAS_DESC} + fastfetch"
[[ "$INSTALL_CLOUDFLARED" == "1" ]] && EXTRAS_DESC="${EXTRAS_DESC} + cloudflared"
[[ "$EFFECTIVE_PACKAGES" == *docker.io* ]] && EXTRAS_DESC="${EXTRAS_DESC} + compose-v2"
log "Packages: ${EFFECTIVE_PACKAGES:-<none>}${EXTRAS_DESC}"

# --------------------------------------------------------------------------- #
# Guest provisioning script — emitted once, consumed by BOTH bake methods:
#   - virt-customize runs it offline in the guest (--run)
#   - the boot method pipes it over SSH into the booted VM
# It installs the apt baseline, sets up cloudflared's apt repo, enables docker,
# and cleans the apt cache. Kept distro-agnostic via /etc/os-release.
# --------------------------------------------------------------------------- #
emit_provision_script() {
  local out="$1"
  local pkgs_space="${EFFECTIVE_PACKAGES//,/ }"
  {
    cat <<'HEAD'
#!/bin/sh
set -eu
export DEBIAN_FRONTEND=noninteractive
log() { echo "[provision] $*"; }

# Fail loudly on a resolver failure instead of letting apt-get update no-op
# (apt can exit 0 with only W: warnings when DNS is broken).
repo_host=deb.debian.org
grep -qi ubuntu /etc/os-release 2>/dev/null && repo_host=archive.ubuntu.com
getent hosts "$repo_host" >/dev/null 2>&1 || { log "ERROR: cannot resolve $repo_host (DNS)"; exit 42; }

log "apt-get update"
apt-get update
HEAD

    if [[ -n "$pkgs_space" ]]; then
      printf 'log "Installing baseline packages"\n'
      printf 'apt-get install -y --no-install-recommends %s\n' "$pkgs_space"
    fi

    if [[ "$INSTALL_CLOUDFLARED" == "1" ]]; then
      cat <<'CF'
log "Installing cloudflared (Cloudflare apt repo)"
. /etc/os-release
CODENAME="${VERSION_CODENAME:-bookworm}"
install -m 0755 -d /usr/share/keyrings
if curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg; then
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared ${CODENAME} main" \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update && apt-get install -y --no-install-recommends cloudflared || log "WARN: cloudflared install failed"
else
  log "WARN: could not fetch cloudflare gpg key; skipping cloudflared"
fi
CF
    fi

    if [[ "$INSTALL_FASTFETCH" == "1" ]]; then
      cat <<'FF'
log "Installing fastfetch (GitHub release .deb — not in Debian 12)"
FF_ARCH=""
case "$(dpkg --print-architecture)" in
  amd64) FF_ARCH=amd64 ;;
  arm64) FF_ARCH=aarch64 ;;
esac
if [ -n "$FF_ARCH" ]; then
  ff_deb="$(mktemp --suffix=.deb)"
  if curl -fsSL "https://github.com/fastfetch-cli/fastfetch/releases/latest/download/fastfetch-linux-${FF_ARCH}.deb" -o "$ff_deb"; then
    apt-get install -y --no-install-recommends "$ff_deb" || { dpkg -i "$ff_deb" || true; apt-get -y -f install || true; }
  else
    log "WARN: could not download fastfetch; skipping"
  fi
  rm -f "$ff_deb"
else
  log "WARN: no fastfetch build for arch $(dpkg --print-architecture); skipping"
fi
FF
    fi

    cat <<'DK'
# Enable docker on boot (offline-safe: only creates symlinks) and add the Compose
# v2 plugin so BOTH `docker compose` (v2) and `docker-compose` (v1 from apt) work.
if dpkg -s docker.io >/dev/null 2>&1; then
  systemctl enable docker >/dev/null 2>&1 || true
  C2_ARCH=""
  case "$(dpkg --print-architecture)" in
    amd64) C2_ARCH=x86_64 ;;
    arm64) C2_ARCH=aarch64 ;;
  esac
  if [ -n "$C2_ARCH" ]; then
    plug_dir=/usr/local/lib/docker/cli-plugins
    install -m 0755 -d "$plug_dir"
    if curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${C2_ARCH}" -o "$plug_dir/docker-compose"; then
      chmod 0755 "$plug_dir/docker-compose"
      log "docker compose v2 plugin installed"
    else
      log "WARN: could not download docker compose v2 plugin (docker-compose v1 still works)"
    fi
  fi
fi
DK

    if [[ "$APT_UPGRADE" == "1" ]]; then
      printf 'log "apt full-upgrade"\napt-get -y -o Dpkg::Options::=--force-confold full-upgrade\n'
    fi

    cat <<'CLEAN'
log "Cleanup"
apt-get -y autoremove --purge || true
apt-get clean
rm -rf /var/lib/apt/lists/*
log "provision done"
CLEAN
  } > "$out"
  chmod +x "$out"
}

# --------------------------------------------------------------------------- #
# Docker builder: bake inside a throwaway container that already has libguestfs +
# qemu, so the host needs nothing but Docker. We re-exec THIS script inside it.
# --------------------------------------------------------------------------- #
docker_daemon_ready() {
  command -v docker >/dev/null 2>&1 || return 1
  docker info >/dev/null 2>&1 || return 1
}

# Resolve whether to bake inside Docker. Prefer a native virt-customize when the
# host already has it; otherwise reach for Docker (the macOS path); fall back to a
# native boot bake only if Docker is unavailable but host qemu is present.
resolve_use_docker() {
  case "$USE_DOCKER" in
    0|1) return ;;
  esac
  if command -v virt-customize >/dev/null 2>&1; then
    USE_DOCKER="0"            # host has the fast tooling already
  elif docker_daemon_ready; then
    USE_DOCKER="1"            # no host libguestfs -> bake in the container
  else
    USE_DOCKER="0"            # last resort: native boot method (needs host qemu)
  fi
}

build_builder_image() {
  local tag="${BUILDER_IMAGE}:${ARCH}"
  if [[ "$REBUILD_BUILDER" != "1" ]] && docker image inspect "$tag" >/dev/null 2>&1; then
    log "Using cached builder image: ${tag}"
    return
  fi
  log "Building builder image ${tag} (one-time; installs libguestfs + qemu)..."
  # No build context needed (nothing is COPY'd) -> feed the Dockerfile on stdin.
  # linux-image-* gives libguestfs a kernel for its supermin appliance; the matching
  # qemu-system is pulled in as a libguestfs-tools dependency. ipxe-qemu provides the
  # virtio option ROMs (efi-virtio.rom) qemu needs once libguestfs attaches a NIC for
  # the network-enabled bake — it's only a Recommends, so --no-install-recommends drops
  # it and the appliance fails to launch ("failed to find romfile efi-virtio.rom").
  docker build --platform "linux/${ARCH}" --build-arg "GUEST_ARCH=${ARCH}" -t "$tag" - <<'DOCKERFILE'
FROM debian:12-slim
ARG GUEST_ARCH=amd64
ENV DEBIAN_FRONTEND=noninteractive LIBGUESTFS_BACKEND=direct
RUN apt-get update && apt-get install -y --no-install-recommends \
      libguestfs-tools "linux-image-${GUEST_ARCH}" ipxe-qemu \
      qemu-utils cloud-image-utils genisoimage \
      openssh-client curl ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*
DOCKERFILE
}

# Append "-v path:path" to MOUNTS_REF only when `path` is NOT already under
# SOURCE_DIR (which we mount whole), to avoid overlapping bind mounts.
add_mount_if_outside() {
  local path="$1"
  [[ -n "$path" ]] || return 0
  case "$path" in
    "$SOURCE_DIR"|"$SOURCE_DIR"/*) return 0 ;;
  esac
  DOCKER_MOUNTS+=(-v "${path}:${path}")
}

run_in_docker() {
  docker_daemon_ready || die "Docker is required but the daemon is not reachable. Start Docker (or run with sudo), or use --no-docker with host qemu installed."
  build_builder_image

  DOCKER_MOUNTS=(-v "${SOURCE_DIR}:${SOURCE_DIR}")
  add_mount_if_outside "$(dirname "$OUT")"
  add_mount_if_outside "$CACHE_DIR"
  add_mount_if_outside "$(dirname "$PUBKEY")"

  local devs=() tcg_env=()
  if [[ -e /dev/kvm ]]; then
    devs+=(--device /dev/kvm)   # KVM accel for libguestfs when the host exposes it
  else
    # No KVM (macOS/OrbStack/Docker Desktop): force software emulation. Without
    # this, on aarch64 libguestfs builds `-machine virt,gic-version=host` and qemu
    # aborts under the TCG fallback ("gic-version=host requires KVM").
    tcg_env+=(-e LIBGUESTFS_BACKEND_SETTINGS=force_tcg)
  fi

  # Cache the supermin appliance across runs so we don't rebuild it every time.
  local gcache="${CACHE_DIR}/.guestfs"
  mkdir -p "$gcache"

  # Allocate a TTY when we have one so the inner script's progress (base-image
  # download, virt-customize steps) streams LIVE instead of sitting in docker's
  # output buffer and looking frozen. Skipped when stdout isn't a tty (cron/CI).
  local tty_flag=()
  [[ -t 1 ]] && tty_flag+=(-t)

  # In verbose mode, also turn on full libguestfs appliance tracing inside the box.
  local verbose_env=()
  [[ "$VERBOSE" == "1" ]] && verbose_env+=(-e LIBGUESTFS_DEBUG=1 -e LIBGUESTFS_TRACE=1)

  log "Baking inside Docker (image ${BUILDER_IMAGE}:${ARCH}, accel=$([[ -e /dev/kvm ]] && echo kvm || echo tcg))..."
  # NOTE: ${arr[@]+"${arr[@]}"} expands a possibly-empty array safely under
  # `set -u` (macOS bash 3.2 errors on a plain "${arr[@]}" when empty).
  docker run --rm \
    ${tty_flag[@]+"${tty_flag[@]}"} \
    ${verbose_env[@]+"${verbose_env[@]}"} \
    ${devs[@]+"${devs[@]}"} \
    ${tcg_env[@]+"${tcg_env[@]}"} \
    ${DOCKER_MOUNTS[@]+"${DOCKER_MOUNTS[@]}"} \
    -e LIBGUESTFS_BACKEND=direct \
    -e LIBGUESTFS_CACHEDIR="${gcache}" \
    -e VM_SSH_USER="${SSH_USER}" \
    -w "${SOURCE_DIR}" \
    "${BUILDER_IMAGE}:${ARCH}" \
    bash "${SCRIPT_PATH}" ${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"} \
      --__in-container --no-docker --method virt-customize \
      --arch "${ARCH}" --pubkey "${PUBKEY}" --out "${OUT}" --cache "${CACHE_DIR}"
}

# Dockerize the whole bake when appropriate, then exit. Everything past this point
# either runs on a host with qemu/libguestfs, or inside the builder container.
if [[ "$IN_CONTAINER" != "1" ]]; then
  resolve_use_docker
  if [[ "$USE_DOCKER" == "1" ]]; then
    # Fast-fail the cheap checks (no qemu needed) before spinning up the container.
    if [[ -f "$OUT" && "$FORCE" != "1" ]]; then
      die "Output already exists: ${OUT} (use --force to overwrite)"
    fi
    run_in_docker
    log "Done (dockerized). Golden image ready: ${OUT}"
    exit 0
  fi
fi

# --------------------------------------------------------------------------- #
# Native preflight (host with qemu/libguestfs, or inside the builder container)
# --------------------------------------------------------------------------- #
command -v qemu-img >/dev/null 2>&1 \
  || die "qemu-img not found. Install QEMU, or rerun with --docker (recommended on macOS)."

if [[ -f "$OUT" && "$FORCE" != "1" ]]; then
  die "Output already exists: ${OUT} (use --force to overwrite)"
fi

# Safety: VMs are qcow2 overlays that reference this base as their backing file.
# Overwriting the base while overlays exist corrupts them. Refuse unless --clobber-base.
if [[ -f "$OUT" && "$CLOBBER_BASE" != "1" ]]; then
  vms_dir="$(cd "$(dirname "$OUT")/.." 2>/dev/null && pwd || true)/vms"
  base_name="$(basename "$OUT")"
  log "Safety check: scanning ${vms_dir} for VM overlays backing onto ${base_name}..."
  deps=()
  if [[ -d "$vms_dir" ]]; then
    for ov in "$vms_dir"/*/disk.qcow2; do
      [[ -e "$ov" ]] || continue
      [[ "$VERBOSE" == "1" ]] && log "  inspecting overlay: ${ov}"
      # -U (force-share) reads metadata WITHOUT taking a file lock, so an overlay
      # held open by a RUNNING VM can never make qemu-img block or error here.
      bk="$(qemu-img info -U "$ov" 2>/dev/null | sed -n 's/^backing file: //p')"
      [[ "$(basename "${bk:-}")" == "$base_name" ]] && deps+=("$ov")
    done
  fi
  log "Safety check done: ${#deps[@]} dependent VM overlay(s) found."
  if (( ${#deps[@]} > 0 )); then
    warn "These VM overlays back onto ${base_name}; rebuilding it WILL corrupt them:"
    for d in "${deps[@]}"; do warn "  - $d"; done
    die "Delete/recreate those VMs first, or pass --clobber-base to overwrite anyway."
  fi
fi

DL() {
  # DL <url> <dest>
  local url="$1" dest="$2"
  if command -v curl >/dev/null 2>&1; then
    # Fail LOUD instead of hanging forever: abort if the connection takes >30s or
    # the transfer drops below 2KB/s for 60s (a stalled mirror used to hang here).
    curl -fL --retry 3 --retry-delay 5 \
         --connect-timeout 30 --speed-limit 2048 --speed-time 60 \
         -o "$dest" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --timeout=30 --tries=3 -O "$dest" "$url"
  else
    die "Neither curl nor wget available to download base image"
  fi
}

# --------------------------------------------------------------------------- #
# Resolve base cloud image URL
# --------------------------------------------------------------------------- #
base_image_url() {
  case "$DISTRO" in
    debian12)
      echo "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-${ARCH}.qcow2"
      ;;
    ubuntu2204)
      local uarch; [[ "$ARCH" == "arm64" ]] && uarch="arm64" || uarch="amd64"
      echo "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-${uarch}.img"
      ;;
    *) die "Unsupported --distro: $DISTRO (debian12|ubuntu2204)" ;;
  esac
}

mkdir -p "$CACHE_DIR" "$(dirname "$OUT")"
BASE_URL="$(base_image_url)"
BASE_IMG="${CACHE_DIR}/$(basename "$BASE_URL")"

if [[ ! -f "$BASE_IMG" ]]; then
  log "Downloading base image: ${BASE_URL}"
  DL "$BASE_URL" "${BASE_IMG}.part"
  mv "${BASE_IMG}.part" "$BASE_IMG"
else
  log "Using cached base image: ${BASE_IMG}"
fi

# Work on a fresh copy, resized to the requested size.
log "Converting base -> ${OUT} (qemu-img convert; can take a moment on a big image)..."
qemu-img convert -O qcow2 "$BASE_IMG" "$OUT"
log "Resizing ${OUT} to ${SIZE_GIB}GiB..."
qemu-img resize "$OUT" "${SIZE_GIB}G" >/dev/null
log "Base image ready; preparing bake config..."

PUBKEY_CONTENT="$(cat "$PUBKEY")"

# sshd drop-in baked into every VM. UseDNS no avoids a reverse-DNS lookup that
# can add seconds to the first SSH handshake.
read -r -d '' SSHD_CONF <<EOF || true
PermitRootLogin yes
PasswordAuthentication no
UseDNS no
GSSAPIAuthentication no
EOF

# systemd-networkd DHCP config (cloud-init no longer configures the NIC).
# Pin public resolvers and ignore DHCP-provided DNS: QEMU slirp DNS (10.0.2.3) is
# unreliable (fails to resolve on macOS hosts) and stalls apt at RUNTIME.
read -r -d '' NETWORK_CONF <<EOF || true
[Match]
Name=en* eth*

[Network]
DHCP=yes
DNS=8.8.8.8
DNS=1.1.1.1

[DHCP]
UseDNS=no
EOF

# Self-contained root-FS growth: replaces cloud-init's cc_growpart (which we
# disable). Needs no network/apt; growpart ships in Debian/Ubuntu cloud images.
read -r -d '' GROWROOT_UNIT <<EOF || true
[Unit]
Description=Grow root filesystem to fill the disk
DefaultDependencies=no
After=systemd-remount-fs.service
Before=local-fs.target sysinit.target
ConditionPathExists=/dev/vda1

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'growpart /dev/vda 1 || true; resize2fs /dev/vda1 || true'

[Install]
WantedBy=multi-user.target
EOF

# --------------------------------------------------------------------------- #
# Choose native method
# --------------------------------------------------------------------------- #
if [[ "$METHOD" == "auto" ]]; then
  if command -v virt-customize >/dev/null 2>&1; then
    METHOD="virt-customize"
  else
    METHOD="boot"
  fi
fi
log "Bake method: ${METHOD}"

# --------------------------------------------------------------------------- #
# Method 1: virt-customize (libguestfs) — fast, no full boot
# --------------------------------------------------------------------------- #
bake_virt_customize() {
  command -v virt-customize >/dev/null 2>&1 || die "virt-customize not found (install libguestfs-tools)"

  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  printf '%s\n' "$SSHD_CONF"     > "${tmp}/pequeroku.conf"
  printf '%s\n' "$NETWORK_CONF"  > "${tmp}/10-dhcp.network"
  printf '%s\n' "$GROWROOT_UNIT" > "${tmp}/growroot.service"
  emit_provision_script "${tmp}/provision.sh"

  local args=(-a "$OUT" --network)
  # -v -x makes libguestfs print every guest command + timing, so a hang inside the
  # appliance is visible (pairs with LIBGUESTFS_DEBUG/TRACE set by run_in_docker).
  [[ "$VERBOSE" == "1" ]] && args+=(-v -x)

  # Create non-root user with sudo + docker, passwordless.
  if [[ "$SSH_USER" != "root" ]]; then
    args+=(--run-command "id ${SSH_USER} >/dev/null 2>&1 || useradd -m -s /bin/bash ${SSH_USER}")
    args+=(--run-command "usermod -aG sudo ${SSH_USER} || true")
    args+=(--run-command "getent group docker >/dev/null || groupadd docker; usermod -aG docker ${SSH_USER} || true")
    args+=(--write "/etc/sudoers.d/90-${SSH_USER}:${SSH_USER} ALL=(ALL) NOPASSWD:ALL")
    args+=(--ssh-inject "${SSH_USER}:file:${PUBKEY}")
  fi
  args+=(--ssh-inject "root:file:${PUBKEY}")

  # sshd + network config
  args+=(--mkdir /etc/ssh/sshd_config.d)
  args+=(--copy-in "${tmp}/pequeroku.conf:/etc/ssh/sshd_config.d")
  args+=(--mkdir /etc/systemd/network)
  args+=(--copy-in "${tmp}/10-dhcp.network:/etc/systemd/network")
  args+=(--run-command "systemctl enable systemd-networkd >/dev/null 2>&1 || true")
  args+=(--run-command "ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf || true")
  args+=(--run-command "systemctl enable systemd-resolved >/dev/null 2>&1 || true")

  # Root-FS auto-grow via self-contained oneshot (no apt needed).
  args+=(--copy-in "${tmp}/growroot.service:/etc/systemd/system")
  args+=(--run-command "systemctl enable growroot.service >/dev/null 2>&1 || true")

  # Install the package set (baseline + cloudflared + extras) inside the guest.
  if [[ -n "$EFFECTIVE_PACKAGES" || "$INSTALL_CLOUDFLARED" == "1" || "$INSTALL_FASTFETCH" == "1" || "$APT_UPGRADE" == "1" ]]; then
    args+=(--run "${tmp}/provision.sh")
  fi

  # SSH host keys, enable ssh, disable cloud-init + the network-online wait.
  args+=(--run-command "ssh-keygen -A")
  args+=(--run-command "systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true")
  args+=(--run-command "touch /etc/cloud/cloud-init.disabled || true")
  args+=(--run-command "systemctl mask cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service >/dev/null 2>&1 || true")
  args+=(--run-command "systemctl mask systemd-networkd-wait-online.service >/dev/null 2>&1 || true")
  args+=(--run-command "systemctl disable apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true")

  log "Running virt-customize (installing packages can take a few minutes)..."
  virt-customize "${args[@]}"
}

# --------------------------------------------------------------------------- #
# Resolve QEMU binary + acceleration + machine for the host/arch (boot method).
# Sets globals: QBIN, ACCEL, MACHINE, QEXTRA (array).
# --------------------------------------------------------------------------- #
QBIN=""; ACCEL=""; MACHINE=""; QEXTRA=()
resolve_qemu() {
  QEXTRA=()
  if [[ "$ARCH" == "arm64" ]]; then
    QBIN="$(command -v qemu-system-aarch64 || true)"
    MACHINE="virt"
    if [[ "$HOST_OS" == "Darwin" ]]; then ACCEL="hvf"
    elif [[ -e /dev/kvm && ( "$HOST_MACHINE" == "aarch64" || "$HOST_MACHINE" == "arm64" ) ]]; then ACCEL="kvm"
    else ACCEL="tcg,thread=multi"; fi
    local uefi
    uefi="$(ls /usr/share/qemu-efi-aarch64/QEMU_EFI.fd \
               /usr/share/AAVMF/AAVMF_CODE.fd \
               /opt/homebrew/share/qemu/edk2-aarch64-code.fd \
               /usr/local/share/qemu/edk2-aarch64-code.fd 2>/dev/null | head -1 || true)"
    [[ -n "${VM_UEFI_ARM64:-}" ]] && uefi="$VM_UEFI_ARM64"
    [[ -n "$uefi" ]] || die "ARM64 UEFI firmware not found; set VM_UEFI_ARM64"
    QEXTRA+=(-bios "$uefi" -cpu max)
  else
    QBIN="$(command -v qemu-system-x86_64 || true)"
    MACHINE="q35"
    if [[ -e /dev/kvm ]]; then ACCEL="kvm"; QEXTRA+=(-cpu host)
    else ACCEL="tcg,thread=multi"; QEXTRA+=(-cpu max); fi
  fi
  [[ -n "$QBIN" ]] || die "QEMU binary for ${ARCH} not found"
}

# --------------------------------------------------------------------------- #
# Method 2: boot once with a one-shot cloud-init that bakes + powers off
# --------------------------------------------------------------------------- #
bake_boot() {
  command -v qemu-img >/dev/null 2>&1 || die "qemu-img required"
  local geniso
  geniso="$(command -v cloud-localds || command -v genisoimage || command -v mkisofs || true)"
  [[ -n "$geniso" ]] || die "Need cloud-localds or genisoimage/mkisofs to build the bake seed"

  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  local sshd_indented network_indented growroot_indented
  sshd_indented="$(printf '%s\n' "$SSHD_CONF" | sed 's/^/      /')"
  network_indented="$(printf '%s\n' "$NETWORK_CONF" | sed 's/^/      /')"
  growroot_indented="$(printf '%s\n' "$GROWROOT_UNIT" | sed 's/^/      /')"

  local extra_user_block=""
  if [[ "$SSH_USER" != "root" ]]; then
    extra_user_block=$(cat <<EOF
  - name: ${SSH_USER}
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: sudo,docker
    shell: /bin/bash
    ssh_authorized_keys:
      - ${PUBKEY_CONTENT}
EOF
)
  fi

  # Packages are installed AFTER the bake over SSH (provision_pass), once the
  # baked-in DNS=8.8.8.8 config is active — during the cloud-init bake the guest is
  # still on QEMU slirp DNS (broken on macOS, hangs apt). So this stays empty.
  cat > "${tmp}/user-data" <<EOF
#cloud-config
disable_root: false
ssh_pwauth: false

users:
  - name: root
    ssh_authorized_keys:
      - ${PUBKEY_CONTENT}
${extra_user_block}

write_files:
  - path: /etc/ssh/sshd_config.d/pequeroku.conf
    owner: root:root
    permissions: '0644'
    content: |
${sshd_indented}
  - path: /etc/systemd/network/10-dhcp.network
    owner: root:root
    permissions: '0644'
    content: |
${network_indented}
  - path: /etc/systemd/system/growroot.service
    owner: root:root
    permissions: '0644'
    content: |
${growroot_indented}

runcmd:
  - systemctl enable systemd-networkd || true
  - systemctl enable growroot.service || true
  - ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf || true
  - systemctl enable systemd-resolved || true
  - ssh-keygen -A
  - systemctl enable ssh || systemctl enable sshd || true
  - systemctl mask systemd-networkd-wait-online.service || true
  - systemctl disable apt-daily.timer apt-daily-upgrade.timer || true
  - touch /etc/cloud/cloud-init.disabled
  - systemctl mask cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service || true
  - cloud-init clean --logs || true
  - poweroff

power_state:
  mode: poweroff
  timeout: 30
  condition: true
EOF

  printf 'instance-id: bake\nlocal-hostname: golden\n' > "${tmp}/meta-data"

  local seed="${tmp}/seed.iso"
  if [[ "$geniso" == *cloud-localds ]]; then
    "$geniso" "$seed" "${tmp}/user-data" "${tmp}/meta-data"
  else
    "$geniso" -output "$seed" -volid cidata -joliet -rock "${tmp}/user-data" "${tmp}/meta-data"
  fi

  resolve_qemu
  log "Booting image once to bake (accel=${ACCEL}); it will self-power-off..."
  "$QBIN" \
    -machine "${MACHINE}" -accel "${ACCEL}" "${QEXTRA[@]}" \
    -smp 2 -m 2048 -nographic \
    -serial "file:${tmp}/bake-console.log" \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -drive "if=virtio,format=qcow2,file=${OUT}" \
    -drive "if=virtio,format=raw,readonly=on,file=${seed}" \
    -no-reboot &
  local qpid=$!

  local waited=0
  while kill -0 "$qpid" 2>/dev/null; do
    sleep 2; waited=$((waited+2))
    if (( waited > BOOT_TIMEOUT )); then
      warn "Bake boot exceeded ${BOOT_TIMEOUT}s; killing QEMU. Check ${tmp}/bake-console.log"
      kill "$qpid" 2>/dev/null || true
      die "Bake timed out"
    fi
  done
  log "Bake boot finished after ~${waited}s"
}

# --------------------------------------------------------------------------- #
# Post-bake SSH provisioning pass (boot method only): run the provision script on
# the booted golden over SSH, with cloud-init OFF and the baked-in DNS active.
# --------------------------------------------------------------------------- #
provision_pass() {
  [[ -f "$PRIVKEY" ]] || die "Private key not found for the SSH provision pass: ${PRIVKEY} (set --privkey)"
  command -v ssh >/dev/null 2>&1 || die "ssh client required for the SSH provision pass"
  resolve_qemu

  local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  emit_provision_script "${tmp}/provision.sh"
  local port=$(( 20000 + (RANDOM % 20000) ))

  log "Provision pass: booting golden (accel=${ACCEL}) to install packages over SSH..."
  "$QBIN" \
    -machine "${MACHINE}" -accel "${ACCEL}" "${QEXTRA[@]}" \
    -smp 2 -m 2048 -nographic \
    -serial "file:${tmp}/provision-console.log" \
    -netdev "user,id=n0,hostfwd=tcp:127.0.0.1:${port}-:22" -device virtio-net-pci,netdev=n0 \
    -drive "if=virtio,format=qcow2,file=${OUT}" \
    -no-reboot &
  local qpid=$!

  local sshopts=(-i "$PRIVKEY" -p "$port" -o StrictHostKeyChecking=no \
                 -o UserKnownHostsFile=/dev/null -o ConnectTimeout=3 -o BatchMode=yes)

  local up=0 waited=0
  while (( waited < BOOT_TIMEOUT )); do
    if ssh "${sshopts[@]}" "${SSH_USER}@127.0.0.1" true 2>/dev/null; then up=1; break; fi
    if ! kill -0 "$qpid" 2>/dev/null; then
      warn "Provision VM exited early. Console tail:"; tail -20 "${tmp}/provision-console.log" >&2; break
    fi
    sleep 2; waited=$((waited+2))
  done
  [[ "$up" == "1" ]] || { kill "$qpid" 2>/dev/null || true; die "Provision pass: SSH never came up"; }

  log "SSH up; running provisioning script (can take a few minutes over NAT)..."
  if ! ssh "${sshopts[@]}" "${SSH_USER}@127.0.0.1" 'sudo sh -s' < "${tmp}/provision.sh"; then
    kill "$qpid" 2>/dev/null || true
    die "apt provisioning failed (see output above)"
  fi

  log "Provisioning complete; powering off the VM..."
  ssh "${sshopts[@]}" "${SSH_USER}@127.0.0.1" 'sudo systemctl poweroff' 2>/dev/null || true

  waited=0
  while kill -0 "$qpid" 2>/dev/null; do
    sleep 2; waited=$((waited+2))
    if (( waited > 180 )); then kill "$qpid" 2>/dev/null || true; break; fi
  done
  log "Provision pass finished."
}

case "$METHOD" in
  virt-customize) bake_virt_customize ;;
  boot)           bake_boot ;;
  *) die "Invalid --method: $METHOD (auto|virt-customize|boot)" ;;
esac

# The boot method couldn't install packages during cloud-init (slirp DNS), so do
# it now over SSH. virt-customize already installed them inline.
if [[ "$METHOD" == "boot" ]]; then
  if [[ -n "$EFFECTIVE_PACKAGES" || "$INSTALL_CLOUDFLARED" == "1" || "$INSTALL_FASTFETCH" == "1" || "$APT_UPGRADE" == "1" ]]; then
    provision_pass
  fi
fi

# Compact the final image.
log "Compacting image..."
qemu-img convert -O qcow2 "$OUT" "${OUT}.tmp" && mv "${OUT}.tmp" "$OUT"
# qemu (the unprivileged vmnet user in prod) reads the base through each VM overlay,
# so it must be world-readable — same reasoning as ensure-base-image.sh.
chmod 0644 "$OUT" 2>/dev/null || true

# Self-describing sidecar so vm_service auto-detects "skip cloud-init" for this base.
write_meta "$OUT"

log "Done. Golden image ready: ${OUT}"
log "Next steps:"
log "  1) Point VM_BASE_IMAGE at ${OUT}"
log "  2) cloud-init is auto-disabled via ${OUT}.meta.json — no VM_USE_CLOUD_INIT"
log "     needed (an explicit VM_USE_CLOUD_INIT env var still overrides if set)"
log "  3) Boot a VM — SSH should be ready in ~10s instead of ~50s"
