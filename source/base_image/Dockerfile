# Dockerfile
FROM ubuntu:latest

# Instalamos Python, Git, curl y limpiamos cachés para aligerar la imagen
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-pip git curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# (Opcional) Hacer python → python3 y pip → pip3
RUN ln -s /usr/bin/python3 /usr/local/bin/python \
    && ln -s /usr/bin/pip3    /usr/local/bin/pip

# Ajusta el WORKDIR si lo necesitas
WORKDIR /app

COPY readme.txt .

# Por defecto abrimos bash
CMD ["/bin/bash"]