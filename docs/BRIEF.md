# TraceFlow: brief do produto

**Real-Time Application Observability Platform**
*Understand your systems. Detect issues faster.*

> Este é o brief original do produto. Onde a implementação difere dele, a decisão e o motivo estão em [DECISOES.md](DECISOES.md):
> - **D23:** o armazenamento é um pipeline próprio. Do Prometheus fica só o `/metrics` do próprio TraceFlow, e o Grafana Tempo não é usado.
> - **D13:** o front segue o brief (Next.js + Tailwind + shadcn/ui).

## 1. Visão geral

O **TraceFlow** é uma plataforma web de observabilidade e monitoramento de aplicações. Ela acompanha a saúde, o desempenho e a comunicação entre APIs e microsserviços em tempo real.

A interface é moderna e interativa, e permite que desenvolvedores:
- identifiquem falhas;
- analisem métricas de desempenho;
- explorem rastreamentos de requisições;
- investiguem incidentes.

É uma aplicação Full Stack inspirada em ferramentas como Datadog, Grafana e New Relic, mas com identidade própria e foco na experiência do desenvolvedor.

## 2. Objetivo

Uma plataforma SaaS de nível profissional que demonstre competências avançadas em:
- desenvolvimento Full Stack;
- arquitetura de software;
- sistemas distribuídos;
- processamento de dados em tempo real;
- DevOps.

É o principal projeto de portfólio, e destaca tanto a qualidade da interface quanto a engenharia por trás da aplicação.

## 3. Público-alvo

- Desenvolvedores Backend e Full Stack.
- Engenheiros de software e DevOps.
- Equipes responsáveis pela manutenção de APIs e microsserviços.
- Empresas que precisam acompanhar a estabilidade de suas aplicações.

## 4. Principais funcionalidades

**Dashboard em tempo real**
- Requisições por segundo.
- Gráficos de latência e tempo de resposta.
- Taxa de erros e indicadores de disponibilidade.
- Atualização automática por WebSockets.

**Monitoramento de serviços**
- Cadastro e gerenciamento de projetos.
- Saúde de diferentes APIs.
- Histórico de desempenho por serviço.
- Filtros por período e ambiente.

**Distributed Tracing**
- Rastreamento de requisições entre microsserviços.
- Tempo gasto em cada operação.
- Identificação de gargalos e falhas.

**Service Dependency Map**
- Mapa interativo das conexões entre serviços.
- Identificação visual de componentes afetados.
- Navegação entre serviços e suas métricas.

**Incident Management**
- Detecção automática de anomalias por regras configuráveis.
- Registro e classificação de incidentes.
- Histórico de eventos e recuperação.
- Investigação das causas com base na telemetria.

**Incident Playground**
- Simulação interativa de falhas reais.
- Geração de tráfego entre microsserviços.
- Impacto dos incidentes.
- Comparação do desempenho antes e depois da recuperação.

## 5. Stack tecnológica

| Área | Tecnologias |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS, shadcn/ui, Recharts, React Flow |
| Backend | Python, FastAPI, SQLAlchemy, WebSockets, Redis |
| Dados e observabilidade | PostgreSQL, Prometheus, OpenTelemetry, Grafana Tempo (ver D23) |
| Infraestrutura e qualidade | Docker / Docker Compose, GitHub Actions, Pytest, Vitest, Playwright |

## 6. Arquitetura

- A arquitetura é modular, com frontend, backend, armazenamento e infraestrutura de observabilidade separados.
- O backend cuida da autenticação, do gerenciamento de projetos, das consultas de telemetria, das regras de incidentes e da comunicação em tempo real.
- Microsserviços simulados geram métricas e traces reais, para testar a plataforma em cenários controlados.

## 7. Identidade visual e experiência

A linguagem visual é **dark-first, minimalista, tecnológica e premium**, inspirada em plataformas profissionais para desenvolvedores.

- Background azul-marinho extremamente escuro (`#0B1020`).
- Superfícies e cards em tons de azul grafite.
- Azul vibrante (`#3B82F6`) como cor principal.
- Verde para indicadores saudáveis.
- Vermelho para erros e incidentes críticos.
- Tipografia Inter e JetBrains Mono.
- Gráficos sofisticados, microinterações e navegação fluida.

A experiência deve transmitir precisão, confiabilidade e sofisticação técnica.

## 8. Diferenciais competitivos

O principal diferencial é poder **simular, acompanhar e investigar incidentes dentro da própria plataforma**, mostrando o funcionamento real de sistemas distribuídos. Não é um dashboard com dados estáticos: é um ambiente funcional de observabilidade, com telemetria, eventos, análises e interações reais.

## 9. Escopo de desenvolvimento

| Fase | Conteúdo |
|---|---|
| 1. Foundation | Infraestrutura, autenticação, arquitetura inicial e design system |
| 2. Telemetry | Instrumentação dos microsserviços e coleta de métricas |
| 3. Dashboard | Indicadores, gráficos e atualização em tempo real |
| 4. Tracing & Incidents | Exploração de traces e identificação de falhas |
| 5. Advanced Experience | Mapa de dependências e simulação interativa de incidentes |
| 6. Production & Portfolio | Testes, documentação, publicação e demonstração pública |

**Prazo estimado:** 12 semanas, com dedicação parcial e escopo controlado. A correspondência entre essas fases e as etapas técnicas está em [ARQUITETURA.md](ARQUITETURA.md#etapas).

## 10. Entregáveis finais

- Plataforma Full Stack funcional.
- Dashboard de observabilidade em tempo real.
- Backend documentado com API REST e WebSockets.
- Ambiente de microsserviços instrumentados.
- Sistema de detecção e investigação de incidentes.
- Simulador interativo de falhas.
- Testes automatizados e pipeline de CI.
- Ambiente reproduzível com Docker.
- Documentação técnica e diagramas de arquitetura.
- Repositório público no GitHub com README profissional.
- Demonstração online acessível a recrutadores.

## 11. Resultado esperado

Demonstrar a capacidade de **projetar, desenvolver, integrar, testar e apresentar uma aplicação Full Stack complexa**, seguindo boas práticas de arquitetura e engenharia de software. É um produto com aparência comercial, funcionalidades reais e profundidade técnica, para se destacar em processos seletivos de **Full Stack Engineer e Software Engineer**.
