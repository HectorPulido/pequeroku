# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS build

ARG FRONT_REACT_BASE=/app/
ENV FRONT_REACT_BASE=${FRONT_REACT_BASE}
WORKDIR /app

RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm run build:ts && pnpm run build:vite

FROM nginx:1.27-alpine AS runtime
WORKDIR /usr/share/nginx/html

ENV NODE_ENV=production
COPY --from=build /app/dist ./
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
HEALTHCHECK CMD wget --spider -q http://127.0.0.1/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
