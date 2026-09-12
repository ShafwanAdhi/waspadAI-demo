FROM node:22-alpine AS dependencies
WORKDIR /workspace/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /workspace
ENV NEXT_TELEMETRY_DISABLED=1
ARG API_ORIGIN=http://api:8001
ENV API_ORIGIN=$API_ORIGIN
COPY --from=dependencies /workspace/apps/web/node_modules ./apps/web/node_modules
COPY apps/web ./apps/web
COPY contracts ./contracts
RUN cd apps/web && npm run api:types && npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /workspace/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000

CMD ["node", "apps/web/server.js"]
