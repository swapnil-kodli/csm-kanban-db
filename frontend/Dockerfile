# --- build ---------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm ci

# BASE_PATH and VITE_API_URL are baked in at `npm run build`, so they must be
# declared and promoted to ENV *before* the build step runs.
ARG BASE_PATH=/
ARG VITE_API_URL=
ENV BASE_PATH=$BASE_PATH
ENV VITE_API_URL=$VITE_API_URL

COPY . .
RUN npm run build

# --- serve ---------------------------------------------------------------
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx resolves `backend` while loading the config, so it refuses to start at
# all ("host not found in upstream") if the backend container has no DNS name
# yet. Wait briefly for the name to appear, then start regardless — a container
# that exits is restarted by compose, but one that never serves the shell is a
# blank page.
COPY docker-entrypoint.sh /docker-entrypoint-signal.sh
RUN chmod +x /docker-entrypoint-signal.sh

EXPOSE 80
CMD ["/docker-entrypoint-signal.sh"]
