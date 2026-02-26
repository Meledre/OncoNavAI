FROM node:20-alpine

WORKDIR /app
ARG NPM_INSTALL_MODE=online
COPY frontend/package.json frontend/package-lock.json* ./
COPY frontend/vendor/npm-cache /opt/npm-cache
RUN set -eux; \
    if [ -f package-lock.json ]; then \
      INSTALL_CMD="npm ci"; \
    else \
      INSTALL_CMD="npm install"; \
    fi; \
    if [ "$NPM_INSTALL_MODE" = "offline" ]; then \
      $INSTALL_CMD --offline --cache /opt/npm-cache --no-audit --no-fund; \
    else \
      $INSTALL_CMD --prefer-offline --cache /opt/npm-cache --no-audit --no-fund; \
    fi

COPY frontend/app /app/app
COPY frontend/components /app/components
COPY frontend/lib /app/lib
COPY frontend/proxy.ts /app/proxy.ts
COPY frontend/next.config.mjs /app/next.config.mjs
COPY frontend/tsconfig.json /app/tsconfig.json
COPY frontend/next-env.d.ts /app/next-env.d.ts
COPY frontend/eslint.config.mjs /app/eslint.config.mjs
ENV NEXT_TELEMETRY_DISABLED=1

CMD ["npm", "run", "dev"]
