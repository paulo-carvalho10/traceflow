# TraceFlow · front

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind 4 + shadcn/ui + TanStack Query.

```bash
npm install
npm run dev          # http://localhost:3000 (a API precisa estar em http://localhost:8000)
npm test             # Vitest
npm run typecheck    # gera os tipos de rota do Next.js e roda o tsc
npm run lint
npm run test:e2e     # Playwright, contra o sistema no ar
npm run api:types    # gera src/lib/api-types.ts a partir do OpenAPI da API
```

- `src/app/`: as rotas (cada pasta é um caminho da URL)
- `src/components/`: as telas e os componentes; `ui/` vem do shadcn/ui
- `src/lib/`: o cliente da API, a formatação, as cores e a matemática do waterfall
- `e2e/`: os testes de ponta a ponta

As cores e as fontes do brief estão em `src/app/globals.css`.
