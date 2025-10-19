FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
COPY . .
RUN npm install
RUN npm run build-only

FROM nginx:1.25-alpine
COPY --from=build /app/dist/dashboard /usr/share/nginx/html/dashboard
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
