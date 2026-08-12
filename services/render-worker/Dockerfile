FROM node:24.18.1-bookworm-slim

ENV NODE_ENV=production \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY package.json package-lock.json tsconfig.json ./
RUN npm ci --include=dev --no-audit --no-fund
RUN printf '%s\n' \
    'Acquire::Retries "8";' \
    'Acquire::http::Timeout "120";' \
    'Acquire::https::Timeout "120";' \
    'Acquire::http::Pipeline-Depth "0";' \
    > /etc/apt/apt.conf.d/80-motif-forge-network
RUN install_attempt=1; \
    until npx playwright install-deps chromium; do \
      if [ "$install_attempt" -ge 5 ]; then exit 1; fi; \
      install_attempt=$((install_attempt + 1)); \
      sleep $((install_attempt * 2)); \
    done; \
    npx playwright install --only-shell chromium; \
    rm -rf /var/lib/apt/lists/*

COPY packages/audio-engine ./packages/audio-engine
COPY services/render-worker ./services/render-worker
COPY scripts/build-render-worker.mjs ./scripts/build-render-worker.mjs

RUN npm run build:audio \
    && npm run test:audio \
    && npm prune --omit=dev \
    && npm cache clean --force

CMD ["node", "services/render-worker/dist/spike.js"]
