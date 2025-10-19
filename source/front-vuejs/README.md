# PequeRoku Dashboard (Vue + TypeScript)

This package contains the Vue 3 + TypeScript rewrite of the PequeRoku dashboard that mirrors the behaviour of the legacy static frontend found in `source/front`.

## Available scripts

```bash
npm install   # install dependencies
npm run dev   # start the Vite dev server
npm run build # type-check and build for production
npm run preview # preview the production build locally
npm run lint  # run Biome static analysis
npm run format # format the codebase with Biome
```

The build generates the dashboard, metrics and IDE pages under the `/dashboard/` base path so it can replace the legacy static
frontend.

## Docker image

The project ships with a multi-stage Dockerfile that builds the Vite assets and serves them through Nginx:

```bash
docker build -t peque-front-vuejs .
```

When used via the repository `docker-compose.yaml`, the resulting container is exposed through the main Nginx gateway under
`/dashboard/`.
