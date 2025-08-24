FROM python:3.13-alpine

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBUG=0

RUN apk add --no-cache \
    gcc musl-dev libffi-dev openssl-dev \
    qemu-system-x86_64 qemu-img cloud-image-utils cdrkit openssh-client \
    postgresql-dev docker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser -D myuser
USER myuser

