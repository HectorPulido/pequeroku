FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies and Podman
RUN apt-get update -qq && \
    apt-get install -y -qq software-properties-common uidmap curl gnupg lsb-release iptables python3-pip git dpkg && \
    . /etc/os-release && \
    echo "deb https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/xUbuntu_${VERSION_ID}/ /" > /etc/apt/sources.list.d/devel:kubic:libcontainers:stable.list && \
    curl -L https://download.opensuse.org/repositories/devel:kubic:libcontainers:stable/xUbuntu_${VERSION_ID}/Release.key | apt-key add - && \
    apt-get update -qq && \
    apt-get install -y podman podman-docker && \
    pip3 install podman-compose

# Install cloudflared
RUN mkdir -p --mode=0755 /usr/share/keyrings && \
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null && \
    echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | tee /etc/apt/sources.list.d/cloudflared.list && \
    apt-get update -qq && \
    apt-get install -y -qq cloudflared

# Configure container registries
COPY registries.conf /etc/containers/registries.conf

# Cleanup
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Symlinks for Python and pip
RUN ln -s /usr/bin/python3 /usr/local/bin/python && \
    ln -s /usr/bin/pip3    /usr/local/bin/pip

WORKDIR /app

# Application files
COPY container_files/ .
COPY docker /usr/local/bin/docker
RUN chmod +x /usr/local/bin/docker

CMD ["/bin/bash"]
