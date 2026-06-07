#!/usr/bin/env bash
#
# build-golden.sh — Build a pre-baked "golden" VM image for pequeroku.
#
# Detects host architecture and OS, downloads the matching cloud base image,
# and bakes everything cloud-init does at runtime directly into the image:
#   - the SSH user (+ root) with the service public key in authorized_keys
#   - the sshd drop-in config (PermitRootLogin yes, no password auth, UseDNS no)
#   - DHCP networking via systemd-networkd
#   - automatic root filesystem growth (cloud-initramfs-growroot)
#   - pre-generated SSH host keys
#   - a baseline of dev tooling (git, pip, venv, build toolchain) so cloned repos
#     configure on the first try, plus any optional --packages extras
# ...then DISABLES cloud-init so runtime boots skip the ~40s pipeline and SSH is
# ready in ~10s. Pair with VM_USE_CLOUD_INIT=false in the vm_service env.
#
# Two baking methods:
#   * virt-customize (libguestfs) — fast, used automatically when available (Linux).
#   * boot           — boots the image once under QEMU with a one-shot cloud-init
#                      that bakes + powers off. Portable (works on macOS/HVF too).
#
# Usage:
#   scripts/build-golden.sh [options]
#
# Options:
#   --distro    <debian12|ubuntu2204>   Guest distro (default: debian12)
#   --arch      <auto|amd64|arm64>      Guest arch (default: auto = host arch)
#   --out       <path>                  Output qcow2 (default: vm_data/base/<distro>-golden.qcow2)
#   --user      <name>                  SSH user to bake (default: $VM_SSH_USER or root)
#   --pubkey    <path>                  Public key to inject (default: $VM_SSH_PRIVKEY.pub or ~/.ssh/id_vm_pequeroku.pub)
#   --size      <GiB>                   Resize image to this size (default: 10)
#   --packages  <csv>                   Extra apt packages on top of the baseline (needs network at bake)
#   --no-base-packages                  Skip the baked-in dev baseline (offline/minimal bake)
#   --apt-upgrade                       Run apt update + full-upgrade on the baked image (needs network)
#   --privkey   <path>                  Private key for the --apt-upgrade SSH pass (default: PUBKEY without .pub)
#   --method    <auto|virt-customize|boot>  Bake method (default: auto)
#   --boot-timeout <secs>               Max wait for the boot/upgrade bake VM (default: 900)
#   --cache     <dir>                   Where to cache downloaded base images (default: vm_data/base/.cache)
#   --force                             Rebuild even if --out already exists
#   --clobber-base                      Allow overwriting a base that live VM overlays back onto (CORRUPTS them)
#   -h | --help                         Show this help
#
set -euo pipefail

# --------------------------------------------------------------------------- #
# Paths / defaults
# --------------------------------------------------------------------------- #
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_SERVICE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEFAULT_BASE_DIR="${VM_SERVICE_DIR}/vm_data/base"

DISTRO="debian12"
ARCH="auto"
OUT=""
SSH_USER="${VM_SSH_USER:-root}"
PUBKEY="${VM_SSH_PRIVKEY:-$HOME/.ssh/id_vm_pequeroku}.pub"
PRIVKEY=""               # private key for the --apt-upgrade pass (default: PUBKEY without .pub)
SIZE_GIB="10"
PACKAGES=""              # extra apt packages, ON TOP of BASE_PACKAGES below
# Baseline dev tooling baked into every golden so cloned repos configure on the
# first try: git to clone, venv+pip to install deps, a compiler + headers for the
# many wheels with C extensions. Installed unless --no-base-packages (needs network
# at bake time, same as --packages). Past failures traced straight to these missing:
# `git: command not found`, venv `ensurepip is not available`, no `pip`.
BASE_PACKAGES="git,curl,ca-certificates,python3-venv,python3-pip,python3-dev,build-essential,docker.io,docker-compose"
NO_BASE_PACKAGES="0"     # set by --no-base-packages to restore the old offline/minimal bake
APT_UPGRADE="0"          # run apt update + full-upgrade on the baked image (needs network)
METHOD="auto"
CACHE_DIR=""
FORCE="0"
CLOBBER_BASE="0"         # allow overwriting a base that live VM overlays depend on
BOOT_TIMEOUT="900"       # max seconds to wait for the boot-method bake VM

log()  { printf '\033[1;34m[build-golden]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[build-golden] WARN:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[build-golden] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,41p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

# --------------------------------------------------------------------------- #
# Parse args
# --------------------------------------------------------------------------- #
while [[ $# -gt 0 ]]; do
  case "$1" in
    --distro)   DISTRO="$2"; shift 2 ;;
    --arch)     ARCH="$2"; shift 2 ;;
    --out)      OUT="$2"; shift 2 ;;
    --user)     SSH_USER="$2"; shift 2 ;;
    --pubkey)   PUBKEY="$2"; shift 2 ;;
    --size)     SIZE_GIB="$2"; shift 2 ;;
    --packages) PACKAGES="$2"; shift 2 ;;
    --no-base-packages) NO_BASE_PACKAGES="1"; shift ;;
    --apt-upgrade) APT_UPGRADE="1"; shift ;;
    --privkey)  PRIVKEY="$2"; shift 2 ;;
    --method)   METHOD="$2"; shift 2 ;;
    --boot-timeout) BOOT_TIMEOUT="$2"; shift 2 ;;
    --cache)    CACHE_DIR="$2"; shift 2 ;;
    --force)    FORCE="1"; shift ;;
    --clobber-base) CLOBBER_BASE="1"; shift ;;
    -h|--help)  usage ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

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
[[ -n "$PRIVKEY" ]]   || PRIVKEY="${PUBKEY%.pub}"

# Effective package list = baked-in baseline (unless --no-base-packages) + extras.
# apt tolerates a name appearing twice, so a plain CSV concat is fine.
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
log "Packages: ${EFFECTIVE_PACKAGES:-<none>}"

# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
[[ -f "$PUBKEY" ]] || die "Public key not found: ${PUBKEY} (set --pubkey or VM_SSH_PRIVKEY)"
command -v qemu-img >/dev/null 2>&1 || die "qemu-img not found (install QEMU)"

if [[ -f "$OUT" && "$FORCE" != "1" ]]; then
  die "Output already exists: ${OUT} (use --force to overwrite)"
fi

# Safety: VMs are qcow2 overlays that reference this base as their backing file.
# Overwriting the base while overlays exist makes those overlays read inconsistent
# data -> filesystem corruption -> the VMs break. Refuse unless --clobber-base.
if [[ -f "$OUT" && "$CLOBBER_BASE" != "1" ]]; then
  vms_dir="$(cd "$(dirname "$OUT")/.." 2>/dev/null && pwd || true)/vms"
  base_name="$(basename "$OUT")"
  deps=()
  if [[ -d "$vms_dir" ]]; then
    for ov in "$vms_dir"/*/disk.qcow2; do
      [[ -e "$ov" ]] || continue
      bk="$(qemu-img info "$ov" 2>/dev/null | sed -n 's/^backing file: //p')"
      [[ "$(basename "${bk:-}")" == "$base_name" ]] && deps+=("$ov")
    done
  fi
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
    curl -fL --retry 3 -o "$dest" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$dest" "$url"
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
      # Debian 12 (bookworm) generic cloud image
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
log "Copying base -> ${OUT} and resizing to ${SIZE_GIB}GiB"
qemu-img convert -O qcow2 "$BASE_IMG" "$OUT"
qemu-img resize "$OUT" "${SIZE_GIB}G" >/dev/null

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
# QEMU's slirp DNS (10.0.2.3) is unreliable — it fails to resolve on macOS hosts
# and stalls apt — so we pin public resolvers and ignore the DHCP-provided DNS.
# DHCP still assigns the IP + routes; only name resolution uses DNS= below.
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
# disable). Needs no network/apt; growpart comes from cloud-guest-utils, which
# Debian/Ubuntu cloud images already ship. The || true keeps boot safe if absent.
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
# Choose method
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

  local args=(-a "$OUT")

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
  # Point resolv.conf at the uplink file (real DHCP DNS), not the 127.0.0.53 stub:
  # the stub listener proved unreliable under QEMU user-net and broke DNS/apt.
  args+=(--run-command "ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf || true")
  args+=(--run-command "systemctl enable systemd-resolved >/dev/null 2>&1 || true")

  # Root-FS auto-grow via self-contained oneshot (no apt needed).
  args+=(--copy-in "${tmp}/growroot.service:/etc/systemd/system")
  args+=(--run-command "systemctl enable growroot.service >/dev/null 2>&1 || true")

  # Baseline + extra packages (needs network at bake time; empty only with
  # --no-base-packages and no --packages, which keeps the bake offline).
  if [[ -n "$EFFECTIVE_PACKAGES" ]]; then
    args+=(--install "${EFFECTIVE_PACKAGES}")
  fi

  # SSH host keys, enable ssh, disable cloud-init + the network-online wait.
  args+=(--run-command "ssh-keygen -A")
  args+=(--run-command "systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1 || true")
  args+=(--run-command "touch /etc/cloud/cloud-init.disabled || true")
  args+=(--run-command "systemctl mask cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service >/dev/null 2>&1 || true")
  args+=(--run-command "systemctl mask systemd-networkd-wait-online.service >/dev/null 2>&1 || true")
  args+=(--run-command "systemctl disable apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true")

  log "Running virt-customize (this can take a minute)..."
  virt-customize "${args[@]}"
}

# --------------------------------------------------------------------------- #
# Resolve QEMU binary + acceleration + machine for the host/arch.
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

  # Indent helpers for embedding multi-line content in YAML.
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

  # NOTE: packages are deliberately NOT installed here via cloud-init. During the
  # cloud-init bake the guest still uses QEMU slirp DNS (10.0.2.3), which is
  # unreliable (it fails to resolve on macOS hosts: apt hangs ~30s per mirror then
  # `Ign`s every InRelease, so nothing installs). They are installed AFTER the bake
  # over SSH (provision_pass), once the baked-in DNS=8.8.8.8 config is active and
  # resolution actually works. So this block stays empty.
  local pkgs_block=""

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

${pkgs_block}
runcmd:
  - systemctl enable systemd-networkd || true
  - systemctl enable growroot.service || true
  - ln -sf /run/systemd/resolve/resolv.conf /etc/resolv.conf || true
  - systemctl enable systemd-resolved || true
  - ssh-keygen -A
  - systemctl enable ssh || systemctl enable sshd || true
  - systemctl mask systemd-networkd-wait-online.service || true
  - systemctl disable apt-daily.timer apt-daily-upgrade.timer || true
  # Disable cloud-init for all future (runtime) boots, then power off.
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

  # Wait for the VM to bake and power off (configurable via --boot-timeout).
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
# Post-bake SSH provisioning pass: apt update, install the package set, and
# optionally full-upgrade — all over SSH against the already-baked golden.
# This runs with cloud-init OFF and the baked-in DHCP+DNS (DNS=8.8.8.8) ACTIVE,
# so name resolution actually works here — unlike during the cloud-init bake,
# where the guest is still on QEMU slirp DNS (broken on macOS, hangs apt). That
# is why the boot method installs packages HERE instead of via cloud-init.
#   $1 = "1" to install $EFFECTIVE_PACKAGES (the boot method; virt-customize
#        already installed them inline on Linux hosts).
# --------------------------------------------------------------------------- #
provision_pass() {
  local do_install="${1:-}"
  [[ -f "$PRIVKEY" ]] || die "Private key not found for the SSH provision pass: ${PRIVKEY} (set --privkey)"
  command -v ssh >/dev/null 2>&1 || die "ssh client required for the SSH provision pass"
  resolve_qemu

  local tmp; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
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

  local repo_host="deb.debian.org"
  [[ "$DISTRO" == ubuntu* ]] && repo_host="archive.ubuntu.com"

  # Build the remote script: always update; install packages and/or full-upgrade
  # as requested; then clean up. The DNS precheck fails loudly instead of letting
  # apt-get update no-op on a resolver failure (apt exits 0 with only W: warnings).
  local remote="export DEBIAN_FRONTEND=noninteractive; set -e;
    getent hosts ${repo_host} >/dev/null || { echo 'DNS FAIL: cannot resolve ${repo_host}'; exit 42; }
    apt-get update;"
  if [[ "$do_install" == "1" && -n "$EFFECTIVE_PACKAGES" ]]; then
    local pkgs_space="${EFFECTIVE_PACKAGES//,/ }"
    log "  will install: ${pkgs_space}"
    remote+="
    apt-get install -y -o Dpkg::Options::=--force-confold ${pkgs_space};"
  fi
  if [[ "$APT_UPGRADE" == "1" ]]; then
    remote+="
    apt-get -y -o Dpkg::Options::=--force-confold full-upgrade;"
  fi
  remote+="
    apt-get -y autoremove --purge;
    apt-get clean"

  log "SSH up; running apt provisioning (can take a few minutes over NAT)..."
  if ! ssh "${sshopts[@]}" "${SSH_USER}@127.0.0.1" "$remote"; then
    kill "$qpid" 2>/dev/null || true
    die "apt provisioning failed (see output above)"
  fi

  log "Provisioning complete; powering off the VM..."
  ssh "${sshopts[@]}" "${SSH_USER}@127.0.0.1" 'systemctl poweroff' 2>/dev/null || true

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
# it now over SSH. virt-customize already installed them inline, so it only needs
# the pass when --apt-upgrade was requested.
PKG_PASS=""
[[ "$METHOD" == "boot" && -n "$EFFECTIVE_PACKAGES" ]] && PKG_PASS="1"
if [[ -n "$PKG_PASS" || "$APT_UPGRADE" == "1" ]]; then
  provision_pass "$PKG_PASS"
fi

# Compact the final image.
log "Compacting image..."
qemu-img convert -O qcow2 "$OUT" "${OUT}.tmp" && mv "${OUT}.tmp" "$OUT"

log "Done. Golden image ready: ${OUT}"
log "Next steps:"
log "  1) Point VM_BASE_IMAGE at ${OUT}"
log "  2) Set VM_USE_CLOUD_INIT=false in the vm_service environment"
log "  3) Boot a VM — SSH should be ready in ~10s instead of ~50s"
