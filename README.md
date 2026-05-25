# Wekams Lens — Community Edition

> One lens. Every data source. Even the logs. Runs in your network.

Wekams Lens is a self-hosted natural-language data agent. Connect it to your
databases, your data lake, and your log files, then ask questions in plain
English. The agent writes SQL, runs it against the right source — or joins
across sources in a single query — and answers with the result.

Everything runs inside your network. With a local LLM, the whole thing is
fully offline.

## What's in the box

- **Backend** — FastAPI + DuckDB query engine + Postgres catalog
- **Frontend** — Next.js chat UI with conversation history and Markdown export
- **Connectors** — Postgres, S3, Azure Blob / ADLS, Google Cloud Storage,
  JSON-lines log files, Elasticsearch / OpenSearch, and a connector SDK
  for writing your own (see [WRITING_CONNECTORS.md](./WRITING_CONNECTORS.md))
- **LLM layer** — pluggable: Ollama for offline, Groq for fast dev
- **Federation** — DuckDB joins across heterogeneous sources in one SQL pass
- **Docker Compose** — bring the whole stack up with one command

## Quick start

```bash
git clone https://github.com/wekams/wekams_Lens.git
cd wekams_Lens
cp .env.example .env          # set GROQ_API_KEY for fast dev, or skip for Ollama
docker compose up --build
```

Open <http://localhost:3000>, register a source on the Sources page, then ask
a question in chat.

## Running fully offline (Ollama)

The dev default is Groq for speed. To run the offline path:

```bash
brew install ollama
brew services start ollama
ollama pull qwen2.5:7b-instruct    # or qwen2.5:3b for an 8 GB machine

# in .env
WEKAMS_LLM_PROVIDER=ollama
WEKAMS_LLM_MODEL_OLLAMA=qwen2.5:7b-instruct
OLLAMA_HOST=http://localhost:11434
```

Restart the backend. The stack is now fully air-gappable — no outbound calls
required at runtime.

## Repository layout

```
wekams_Lens/
├── backend/        FastAPI app + DuckDB engine + connectors
├── frontend/       Next.js chat UI
├── connectors/     External / community connectors
├── scripts/        Demo data seeders
└── docker-compose.yml
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the design and
[WRITING_CONNECTORS.md](./WRITING_CONNECTORS.md) to ship your own connector.

## License

Apache 2.0 — see [LICENSE](./LICENSE).

## Contributing

Issues and discussions are welcome. PRs against the connector SDK and the
demo seed scripts are the easiest first contributions. Larger changes:
please open an issue first to discuss direction.
