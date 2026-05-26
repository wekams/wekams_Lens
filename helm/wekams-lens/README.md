# Wekams Lens — Helm chart

Deploys [Wekams Lens](https://wekams.com/lens/) on any Kubernetes cluster.
Works for both Community (free) and Pro / Enterprise (licensed) editions —
just swap the image repository and provide a license.

## Prerequisites

- Kubernetes 1.27+
- Helm 3.12+
- A namespace you control (`kubectl create namespace wekams`)
- For production: a managed Postgres database (the chart can also run a
  bundled Postgres for trials)
- A way to expose the service (Ingress controller, or `kubectl port-forward`)

## Quick install — Community trial

```bash
helm install lens ./helm/wekams-lens \
  --namespace wekams --create-namespace \
  --set auth.token=$(openssl rand -hex 32) \
  --set postgres.mode=bundled
```

Then port-forward and visit:

```bash
kubectl --namespace wekams port-forward svc/lens-wekams-lens-frontend 3000:3000
open http://localhost:3000
```

## Production install — Pro / Enterprise

Create a values override file (`values.prod.yaml`) — example:

```yaml
edition: pro

image:
  repository: ghcr.io/wekams/lens-pro      # Your private Pro image
  tag: "0.1.0"
  pullSecrets:
    - name: wekams-pull                     # kubectl create secret docker-registry ...

auth:
  token: "<generated-strong-token>"

license:
  file: "wekams.lic.v1.eyJ...<full-license-token>"

postgres:
  mode: external
  url: "postgresql+asyncpg://wekams:STRONG@postgres.internal:5432/wekams_catalog"

llm:
  provider: ollama
  ollamaHost: "http://ollama.shared.svc.cluster.local:11434"
  ollamaModel: "qwen2.5:7b-instruct"

ingress:
  enabled: true
  host: lens.your-domain.example
  tls:
    enabled: true
    secretName: lens-tls
```

Install:

```bash
helm install lens ./helm/wekams-lens -n wekams -f values.prod.yaml
```

## Upgrading

```bash
helm upgrade lens ./helm/wekams-lens -n wekams -f values.prod.yaml
```

## What gets deployed

| Resource | Count | Purpose |
|---|---|---|
| Deployment `<release>-backend` | 1 (configurable) | FastAPI + DuckDB engine + connectors |
| Deployment `<release>-frontend` | 1 (configurable) | Next.js chat UI |
| Deployment `<release>-postgres` | 0 or 1 | Bundled catalog DB (only if `postgres.mode=bundled`) |
| PVC `<release>-postgres` | 0 or 1 | Bundled Postgres data (only if bundled) |
| Service `<release>-backend` | 1 | ClusterIP on port 8000 |
| Service `<release>-frontend` | 1 | ClusterIP on port 3000 |
| Service `<release>-postgres` | 0 or 1 | ClusterIP on port 5432 (only if bundled) |
| ConfigMap `<release>-config` | 1 | Non-secret env (LLM provider, log level, etc.) |
| Secret `<release>-secrets` | 1 | Auth token, DB URL, license, LLM keys |
| Ingress `<release>` | 0 or 1 | Routes `/` → frontend, `/api/*` → backend |
| ServiceAccount `<release>-wekams-lens` | 0 or 1 | Pod identity |

## Air-gap deployments

For fully airgapped clusters:

1. Use `llm.provider=ollama` (no external API calls)
2. Run an in-cluster Ollama and point `llm.ollamaHost` at it
3. Pre-pull the Lens image into your cluster's internal registry, then set
   `image.repository` to your registry path
4. Use `postgres.mode=external` and point at your internal Postgres

The Lens chart itself never reaches out to the public internet at runtime.

## Resource sizing

Defaults are sized for a single-team trial (~10 users). For larger
deployments, bump replicas + resources in `values.yaml`:

```yaml
backend:
  replicas: 3
  resources:
    requests: { cpu: 1,    memory: 2Gi }
    limits:   { cpu: 4,    memory: 8Gi }
frontend:
  replicas: 2
  resources:
    requests: { cpu: 200m, memory: 512Mi }
    limits:   { cpu: 1,    memory: 2Gi }
```

## Uninstall

```bash
helm uninstall lens -n wekams
# If postgres.mode=bundled, the PVC is left behind. Remove it to wipe data:
kubectl delete pvc lens-wekams-lens-postgres -n wekams
```
