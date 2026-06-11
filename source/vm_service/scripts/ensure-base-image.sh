#!/usr/bin/env bash
#
# ensure-base-image.sh — guarantee a bootable base image exists at VM_BASE_IMAGE.
#
# Resolution:
#   - File already exists -> do nothing. VM overlays back onto it; never overwrite.
#   - Missing + VM_AUTODOWNLOAD_IMAGE=false -> fail fast with a clear message.
#   - Missing otherwise -> download the official Debian 12 genericcloud image for
#     this host arch (same source build-golden.sh uses), verify its SHA512, publish
#     it atomically, and drop a "golden": false sidecar so vm_service runs cloud-init
#     for it (slow ~50s path, but a clean machine boots VMs with zero prep).
#
# Build a golden later (scripts/build-golden.sh) to cut boot to ~10s.
#
set -euo pipefail

VM_BASE_IMAGE="${VM_BASE_IMAGE:-/app/vm_data/base/debian12-golden.qcow2}"
VM_SSH_USER="${VM_SSH_USER:-root}"
AUTODOWNLOAD="$(printf '%s' "${VM_AUTODOWNLOAD_IMAGE:-true}" | tr '[:upper:]' '[:lower:]')"

log()  { printf '\033[1;34m[ensure-base]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[ensure-base] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

if [ -f "$VM_BASE_IMAGE" ]; then
  log "Base image present: $VM_BASE_IMAGE (left untouched)"
  exit 0
fi

case "$AUTODOWNLOAD" in
  0|false|no|off)
    die "No base image at $VM_BASE_IMAGE and VM_AUTODOWNLOAD_IMAGE is off.
  Build one with vm_service/scripts/build-golden.sh, or set VM_AUTODOWNLOAD_IMAGE=true."
    ;;
esac

# Map host arch -> Debian cloud arch (same mapping as build-golden.sh).
case "$(uname -m)" in
  x86_64|amd64)  DEB_ARCH="amd64" ;;
  aarch64|arm64) DEB_ARCH="arm64" ;;
  *) die "Unsupported host arch $(uname -m); build the base manually with build-golden.sh" ;;
esac

BASE_URL="https://cloud.debian.org/images/cloud/bookworm/latest"
IMG="debian-12-genericcloud-${DEB_ARCH}.qcow2"
URL="${BASE_URL}/${IMG}"
SUMS_URL="${BASE_URL}/SHA512SUMS"

dest_dir="$(dirname "$VM_BASE_IMAGE")"
mkdir -p "$dest_dir"
tmp_img="$(mktemp "${dest_dir}/.dl.XXXXXX")"
tmp_sums="$(mktemp)"
cleanup() { rm -f "$tmp_img" "$tmp_sums"; }
trap cleanup EXIT

log "No base image found. Downloading ${IMG} (~350MB); first boots use the"
log "cloud-init slow path (~50s). Build a golden later for ~10s boots."
log "GET ${URL}"
curl -fL --retry 3 -o "$tmp_img" "$URL" || die "Download failed: $URL"

log "Verifying SHA512 against ${SUMS_URL}"
curl -fsL --retry 3 -o "$tmp_sums" "$SUMS_URL" || die "Could not fetch SHA512SUMS"
expected="$(awk -v f="$IMG" '$2 == f {print $1}' "$tmp_sums" | head -n1)"
[ -n "$expected" ] || die "No SHA512 entry for ${IMG} in SHA512SUMS"
actual="$(sha512sum "$tmp_img" | awk '{print $1}')"
[ "$expected" = "$actual" ] || die "Checksum mismatch for ${IMG} (expected ${expected:0:16}..., got ${actual:0:16}...)"
log "Checksum OK"

# Atomic publish (same dir = same filesystem), then the golden:false sidecar.
# mktemp makes the temp 0600; qemu runs as the unprivileged vmnet user and must
# read the base through each VM overlay, so make it world-readable.
mv "$tmp_img" "$VM_BASE_IMAGE"
chmod 0644 "$VM_BASE_IMAGE"
cat > "${VM_BASE_IMAGE}.meta.json" <<EOF
{
  "golden": false,
  "distro": "debian12",
  "arch": "${DEB_ARCH}",
  "ssh_user": "${VM_SSH_USER}",
  "source": "${URL}",
  "builder": "ensure-base-image.sh"
}
EOF
log "Base image ready: $VM_BASE_IMAGE (cloud-init mode)"
