# O front do TraceFlow em produção (fora da Vercel): um servidor Node com o build "standalone".
# Em duas fases: a primeira tem as ferramentas de build; a segunda, só o que roda.

FROM node:24.21.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts          # instala exatamente o que está no lock
COPY . .
# O endereço da API entra no JavaScript na hora do build (variáveis NEXT_PUBLIC_*)
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_INGEST_URL=http://localhost:4318
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_INGEST_URL=$NEXT_PUBLIC_INGEST_URL NEXT_TELEMETRY_DISABLED=1
RUN npx next build

FROM node:24.21.0-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
