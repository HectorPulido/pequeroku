# Create a qcow2 image

This guide is compatible with arm64 and x86_64 and will help you create a .qcow2 image.

## Prerequisites

This guide is for Linux. The software can be used on macOS or other UNIX-like systems, but image creation requires Linux.
First, install the required packages (Debian/Ubuntu shown; adapt to your distro).

1. If you use x86_64 architecture, use:
```bash
sudo apt-get update
sudo apt-get install -y qemu-kvm qemu-utils cloud-image-utils genisoimage \
                        libvirt-daemon-system libvirt-clients libvirt
```

2. If you use arm64 architecture (e.g., Raspberry Pi or Orange Pi), use:
```bash
sudo apt-get update
sudo apt-get install -y \
    qemu-utils qemu-system-aarch64 qemu-efi-aarch64 libguestfs-tools cloud-image-utils \
    util-linux kpartx curl gnupg ca-certificates
```

## Download the base image

In this case we will use Debian, but other distros can be used; just search for "<my distro> genericcloud <my arch>"

1. If you use x86_64 architecture, use:
```bash
curl -LO https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2
mv debian-12-genericcloud-amd64.qcow2 debian-raw.qcow2
```

2. If you use arm64 architecture (e.g., Raspberry Pi or Orange Pi), use:
```bash
curl -LO https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-arm64.qcow2
mv debian-12-genericcloud-arm64.qcow2 debian-raw.qcow2
```

## Then let's generate the chroot

```bash
# Load the NBD kernel module with partition support
sudo modprobe nbd max_part=16

# Attach the qcow2 image to /dev/nbd0
sudo qemu-nbd -c /dev/nbd0 debian-raw.qcow2

# Get the root partition, it's usually `/dev/nbd0p1`.
lsblk /dev/nbd0 -o NAME,SIZE,TYPE,MOUNTPOINTS

sudo mkdir -p /mnt/img
sudo mount /dev/nbd0p1 /mnt/img

# Prepare the chroot environment
sudo mount --bind /dev  /mnt/img/dev
sudo mount --bind /proc /mnt/img/proc
sudo mount --bind /sys  /mnt/img/sys
sudo mount --bind /run  /mnt/img/run
sudo cp /etc/resolv.conf /mnt/img/etc/resolv.conf
sudo chroot /mnt/img /bin/bash
```

## In this step we are already **inside the Debian guest**
Run your customizations there (you can change them)...
In this example we install Docker, Cloudflared, Python, and Git

```bash
set -euo pipefail

apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release

# Docker
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker-ce.gpg
chmod a+r /etc/apt/keyrings/docker-ce.gpg
sh -c 'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker-ce.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list'

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable docker || true

# Cloudflared
install -m 0755 -d /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list

apt-get update
apt-get install -y cloudflared

# Extra tools
apt-get install -y python3 python3-pip git

# Optional cleanup to reduce image size
apt-get clean
rm -rf /var/lib/apt/lists/*
truncate -s 0 /var/log/*.log || true

exit
```

## Now we have an image...
Now it's time to clean up and detach

```bash
sudo umount -R /mnt/img
sudo qemu-nbd -d /dev/nbd0
sudo qemu-img convert -O qcow2 debian-raw.qcow2 debian12-golden.qcow2

# Move into the repository's VM base directory used by Docker Compose
mkdir -p ./source/vm_data/base/
mv -v debian12-golden.qcow2 ./source/vm_data/base/
```

## Finishing...
Now we have debian12-golden.qcow2. You can use it on the platform by following the [README instructions](README.md).. In Docker Compose, VM_BASE_IMAGE should point to /app/vm_data/base/debian12-golden.qcow2 (this is the default in source/docker-compose.yaml).
