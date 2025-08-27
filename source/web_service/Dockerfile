FROM --platform=$BUILDPLATFORM python:3.13-slim

ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBUG=0

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential gcc libc6-dev libffi-dev libssl-dev libpq-dev \
      qemu-utils cloud-image-utils genisoimage openssh-client \
      curl ca-certificates ca-certificates iproute2 iptables && \
    case "$TARGETARCH" in \
      amd64) \
        apt-get install -y --no-install-recommends qemu-system-x86 ovmf \
        ;; \
      arm64) \
        apt-get install -y --no-install-recommends qemu-system-arm qemu-efi-aarch64 ipxe-qemu qemu-system-data \
        ;; \
      *) echo "Unsupported TARGETARCH: $TARGETARCH" && exit 1 ;; \
    esac && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
