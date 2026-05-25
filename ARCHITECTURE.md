# Wekams Lens — Architecture

This document describes the Community Edition's architecture: the components
that ship in this repository, how they fit together, and the design choices
behind them. It's meant for contributors and self-hosters.

## 1. System overview

```
              ┌─────────────────────────────────────────────┐
              │            User's browser (Next.js UI)       │
              └────────────────┬────────────────────────────┘
                               │ HTTPS / JSON / SSE
              ┌────────────────▼────────────────────────────┐
              │          FastAPI backend                     │
              │  ┌───────────────────────────────────────┐  │
              │  │       Agent orchestrator               │  │
              │  │  - schema context builder              │  │
              │  │  - tool registry                       │  │
              │  │  - federated SQL planner               │  │
              │  └────┬──────────────────────────────┬───┘  │
              │       │                              │      │
              │   ┌───▼─────┐                ┌───────▼───┐  │
              │   │  LLM    │                │  DuckDB   │  │
              │   │ Ollama  │                │ engine    │  │
              │   │ or Groq │                │ (federate)│  │
              │   └─────────┘                └─────┬─────┘  │
              │                                    │        │
              │            ┌───────────────────────┴──┐     │
              │            │     Connector layer       │     │
              │            │  Postgres / S3 / Azure /  │     │
              │            │  GCS / logs / ES / SQLite │     │
              │            └─────────────┬─────────────┘     │
              └──────────────────────────┼───────────────────┘
                                         │
              ┌──────────────────────────▼───────────────────┐
              │   Your existing data systems (read-only)     │
              └───────────────────────────────────────────────┘

           Postgres catalog: source registry, conversations, metadata
```

Everything sits inside one network boundary. The LLM call is the only
network hop that could leave that boundary — and with Ollama, even that
stays local.

## 2. Components

### 2.1 Frontend (`frontend/`)

Next.js App Router, TypeScript, Tailwind. Two main routes:

- **`/`** — chat. Streams the agent's response token-by-token via SSE, shows
  tool calls (SQL, source) in expandable panels, and renders results as
  tables.
- **`/sources`** — register and inspect data sources. Each source type has
  its own form schema delivered by the backend.

State lives in React + lightweight `lib/*.ts` API clients that wrap
the backend's REST endpoints. Conversations are persisted server-side; the
URL of any conversation is its permanent shareable link.

### 2.2 Backend (`backend/app/`)

FastAPI, Python 3.11+, async-first.

- **`api/`** — REST + SSE endpoints: `chat`, `conversations`, `sources`, `health`
- **`orchestrator/`** — the agent. Tools the LLM can call (`run_sql`,
  `query_federated`), the SQL planner, and the per-turn schema-context
  builder
- **`llm/`** — provider factory. Two backends: `ollama_backend.py` (offline,
  production default) and `groq_backend.py` (fast cloud, for dev)
- **`connectors/`** — one module per source type. All implement a small
  `BaseConnector` contract (`describe`, `list_tables`, `get_schema`,
  `run_sql`). See [WRITING_CONNECTORS.md](./WRITING_CONNECTORS.md)
- **`catalog/`** — Postgres catalog (SQLAlchemy + Alembic). Stores source
  configs, conversations, messages, and the encrypted credential vault
- **`core/`** — config, logging

### 2.3 Federation

A single DuckDB process inside the backend acts as the federation engine.
When a question touches more than one source, the orchestrator builds one
SQL statement using DuckDB's native features:

- `ATTACH` to read directly from Postgres
- `read_parquet` / `read_csv` for S3, Azure Blob, GCS
- `read_json` (line-delimited) for log files
- HTTP / Query DSL for Elasticsearch (custom UDF)

The result is one round-trip that joins across heterogeneous sources without
materialising intermediate datasets. The plan is visible in the chat UI so a
user can audit what ran.

### 2.4 Catalog

A small Postgres database, bundled in the Docker Compose stack, holds:

- Registered sources (type, connection params, encrypted secrets)
- Conversations and their messages
- Tool-call records (SQL run, source picked, result row count)

It's deliberately small. The product is largely stateless — restart it and
nothing important is lost beyond conversation history.

### 2.5 Credential vault

Source secrets are encrypted at rest using a key stored in `.env`. Nothing
sensitive is logged. Secrets never leave the backend process — the frontend
sees only field names and masked previews.

## 3. Data flow for a single question

1. User types in chat → POST `/api/chat`
2. Backend assembles schema context: every registered source's table list
   and column types, filtered by relevance
3. Schema + question + tool definitions go to the LLM (Ollama or Groq)
4. LLM responds with a tool call (`run_sql` or `query_federated`)
5. Backend runs the SQL against the appropriate connector(s); DuckDB
   federates if needed
6. Result rows + the SQL itself are streamed back to the frontend
7. LLM gets the result and streams a natural-language explanation
8. Everything is persisted to the catalog under a conversation ID

## 4. LLM choice

Two backends ship out of the box:

| Backend | Where it runs | Use for |
|---|---|---|
| Ollama | Customer hardware (CPU or GPU) | Production / air-gap |
| Groq | Public API | Fast dev iteration |

The interface is one Python protocol (`LLMBackend`) — adding vLLM,
llama.cpp, or any other endpoint is a single module.

Recommended Ollama models:

| Model | RAM | Suitable for |
|---|---|---|
| `qwen2.5:3b` | ~2 GB | 8 GB machines, single-tool tasks |
| `qwen2.5:7b-instruct` | ~5 GB | 16 GB machines, production default |
| `qwen2.5:14b` and up | 16 GB+ / GPU | Larger deployments |

## 5. Connector model

Every source is a Python class implementing the same protocol. The
[WRITING_CONNECTORS.md](./WRITING_CONNECTORS.md) guide walks through it
end-to-end. Out-of-the-box, the following ship:

- Postgres (also MySQL via the same JDBC-style approach)
- S3 (Parquet, CSV, JSON)
- Azure Blob Storage / ADLS Gen2
- Google Cloud Storage
- JSON-lines log files (local filesystem)
- Elasticsearch / OpenSearch (Query DSL native)
- SQLite (as a reference connector plugin in `connectors/external/`)

## 6. Security

- Read-only by design. Connectors don't expose write paths.
- Credentials encrypted at rest, never logged.
- SQL is shown to the user before/after execution — nothing is hidden.
- No telemetry, no phone-home, no analytics.
- Default deployment listens only on localhost; binding to public
  interfaces is opt-in.

## 7. Deployment

The reference deployment is Docker Compose: backend, frontend, Postgres,
and (optionally) Ollama, all on one host. For larger or
high-availability setups, split the stack across hosts and put the
catalog on managed Postgres.

## 8. What's deliberately not here

- No managed control plane, no cloud account, no SaaS dependencies.
- No vector store. Schema-driven SQL planning gets you further than RAG
  for this problem class; we may add embeddings later for source ranking.
- No write path to source systems. Lens is a read-only analyst.
