# Build stage
FROM node:20-slim AS build
WORKDIR /app
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
# Runtime API URLs are baked in at build time (Vite env vars are inlined
# into the bundle, not read at container-start like a backend's env vars).
# docker-compose.yml passes these as build args -- rebuild the image if
# you change where llm-service lives, a plain container restart won't
# pick up a new VITE_LLM_SERVICE_URL.
ARG VITE_LLM_SERVICE_URL=http://localhost:8001
ENV VITE_LLM_SERVICE_URL=$VITE_LLM_SERVICE_URL
RUN npm run build

# Runtime stage
FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
