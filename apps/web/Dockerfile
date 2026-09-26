FROM node:22-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1

# --- deps ---
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
# Reproducible install when a lockfile is committed; plain install otherwise
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# --- build ---
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* values are inlined into the browser bundle at build time
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN mkdir -p public && npm run build

# --- runtime ---
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app

COPY --from=builder /app/public ./public
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static

USER app
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -qO /dev/null http://127.0.0.1:3000/healthz || exit 1

CMD ["node", "server.js"]
