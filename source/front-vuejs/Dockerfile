FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.25-alpine
COPY --from=build /app/dist/dashboard /usr/share/nginx/html/dashboard
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
