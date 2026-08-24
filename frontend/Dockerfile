# --- build ---------------------------------------------------------------
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
# `npm ci` has been observed to crash with "Exit handler never called!" and
# still exit 0, leaving node_modules incomplete. The build then dies further
# down with a confusing "tsc: not found". Verify the toolchain is actually
# present so a broken install fails here, loudly, instead of shipping.
RUN npm ci && npx --no-install tsc --version && npx --no-install vite --version

# BASE_PATH and VITE_API_URL are baked in at `npm run build`, so they must be
# declared and promoted to ENV *before* the build step runs.
#
# Both default to EMPTY, not "/". A "/" default is worse than no value at all:
# it is truthy, so it silently wins over every fallback and bakes root-absolute
# /assets/... into index.html. The marketplace routes anything outside
# /p/{slug}/ to its own app, which answers 200 text/html, so the browser
# rejects the module and the page renders blank with no console error.
# Empty lets vite.config.ts fall back to a relative base that works under any
# mount point. Pass --build-arg BASE_PATH=/p/{slug}/ to pin it explicitly.
ARG BASE_PATH=
ARG VITE_API_URL=
ENV BASE_PATH=$BASE_PATH
ENV VITE_API_URL=$VITE_API_URL

COPY . .
RUN npm run build

# INSTRUCTIONS.md §9: the built index.html must not reference /assets/... .
# Enforce it here so a bad base path fails the build instead of shipping a
# blank page that only shows up after deployment.
RUN if grep -qE '(src|href)="/assets/' dist/index.html; then \
      echo "FATAL: index.html references root-absolute /assets/ — this blanks on marketplace." >&2; \
      grep -oE '(src|href)="[^"]*"' dist/index.html >&2; \
      exit 1; \
    fi

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
