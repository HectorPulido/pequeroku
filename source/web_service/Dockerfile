FROM python:3.13-alpine

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBUG=0

# Instalar dependencias del sistema
RUN apk add --no-cache gcc postgresql-dev docker

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN adduser -D myuser
USER myuser

