# PequeRoku — Landing

This directory contains PequeRoku’s public landing site. It is a static site with no build step, designed to be served by Nginx alongside the rest of the platform.

- Location: source/landing
- Source: source/landing/page/*
- Tooling: Biome for lint/format (no bundler)
- Integration: served together with the Dashboard (frontend), Web Service (Django), and VM Service (FastAPI) via Docker Compose + Nginx

## How Nginx serves this folder

The file source/nginx/default.conf maps this folder to public root:

- Landing routes:
  - / → index.html under /usr/share/nginx/landing (mounted from source/landing/page)
  - /terms → terms.html
  - /privacy → privacy.html
  - Any direct asset under / is served from /usr/share/nginx/landing if present
- Dashboard (frontend):
  - /dashboard/ → index.html (mounted from source/front)
  - /dashboard/ide/ → ide.html
  - /dashboard/metrics/ → metrics.html
- Backend static:
  - /static/ → /usr/share/nginx/static (mounted from source/web_service/staticfiles)
- Proxies to Django:
  - /api/, /media/, /admin/
- WebSockets:
  - /ws/ → proxied to Django/Channels with Upgrade headers

In docker-compose.yaml, the Nginx container mounts:

- ./landing/page:/usr/share/nginx/landing:ro (this landing)
- ./front/page:/usr/share/nginx/html:ro (dashboard)
- ./web_service/staticfiles:/usr/share/nginx/static:ro (Django static)

The landing’s “Get Started” button points to /dashboard/ (served by source/front).

## Directory structure (landing)

- page/index.html — Home (hero, features, demo video)
- page/docs.html — Docs/Recipes demo (component kit)
- page/privacy.html — Privacy policy
- page/terms.html — Terms of service
- page/styles.css — Base styles and components
- page/main.js — Interactions (theme toggle, tabs, copy-to-clipboard, responsive menu)
- page/favicon.svg — Site icon
- page/utils/ — Auxiliary assets (e.g., demo.mp4)
- package.json — Biome scripts (lint/format/check/fix)
- biome.json, .biomeignore — Biome configuration

No bundler: assets are loaded directly by the browser.

## Local development

Option A — Run the full stack with Docker Compose (recommended)

1) From source/:
   - docker compose up -d
2) Open:
   - Landing: http://localhost/
   - Dashboard: http://localhost/dashboard/
3) Edit files under source/landing/page/* and refresh the browser.

Option B — Preview the landing as static files only

- Open source/landing/page/index.html directly in your browser.
- Note: links like /dashboard/ and backend proxies only work behind Nginx/Compose.

## Biome commands

From source/landing/package.json:

- Install: npm ci
- Lint: npm run lint
- Format: npm run format
- Check (lint + format): npm run check
- Fix (autofix): npm run fix

Note: Biome covers JS/JSON; HTML/CSS may not be formatted automatically.

## Routes and navigation

- “Get Started” → /dashboard/
- Docs/GitHub links → public repo/docs
- “Pretty” paths without .html (e.g., /terms, /privacy) are mapped in default.conf using exact location rules.

## Customization

- Branding: update logo/emoji and name in page/index.html.
- SEO/Head: update <title> and <meta name="description"> in page/*.html.
- Theme/colors: adjust CSS variables in page/styles.css; theme toggle logic is in page/main.js.
- Media: replace page/utils/demo.mp4 with your own demo if desired.

## Adding new pages

1) Create a new .html file under page/ (e.g., pricing.html).
2) Link it in the header or relevant sections.
3) If you want a route without “.html” (e.g., /pricing), add a rule to source/nginx/default.conf:

    location = /pricing {
      root /usr/share/nginx/landing;
      try_files /pricing.html =404;
    }

4) Reload Nginx if you changed the config (in Compose: recreate the service or run nginx -s reload inside the container).

## Troubleshooting

- 404 at /: ensure ./landing/page is mounted to /usr/share/nginx/landing and index.html exists.
- CSS/JS not applied: verify <link>/<script> paths and that Nginx serves / from /usr/share/nginx/landing.
- “Get Started” broken: confirm /dashboard/ is mapped in default.conf and the Nginx container depends on the web (Django) service.
- Video not loading: check page/utils/demo.mp4 exists and that the browser supports MP4.
- WebSockets failing: confirm location /ws/ has proper Upgrade/Connection headers and points to Django.

## Security and best practices

- This landing is static; it does not process user data.
- In production, serve via HTTPS and add common security headers at Nginx (CSP, HSTS, etc.).
- Keep assets lean (optimize images/videos) for good performance and Core Web Vitals.
