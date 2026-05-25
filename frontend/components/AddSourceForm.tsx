"use client";

import { useEffect, useState } from "react";
import {
  createSource,
  listSourceTypeDetails,
  testConnection,
  type SourceTypeDetail,
  type SourceView,
} from "@/lib/sources";

type Props = {
  onCreated: (s: SourceView) => void;
  onCancel: () => void;
};

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok" }
  | { kind: "fail"; message: string };

const KNOWN_FORMS = new Set([
  "postgres",
  "s3",
  "azure_blob",
  "gcs",
  "logs",
  "elasticsearch",
]);

export default function AddSourceForm({ onCreated, onCancel }: Props) {
  const [types, setTypes] = useState<SourceTypeDetail[]>([]);
  const [typesError, setTypesError] = useState<string | null>(null);
  const [type, setType] = useState<string>("postgres");

  useEffect(() => {
    listSourceTypeDetails().then(
      (ts) => {
        setTypes(ts);
        if (!ts.find((t) => t.type === "postgres") && ts.length > 0) setType(ts[0].type);
      },
      (e) => setTypesError(e instanceof Error ? e.message : String(e)),
    );
  }, []);

  const [name, setName] = useState("");

  // Postgres fields
  const [pgHost, setPgHost] = useState("localhost");
  const [pgPort, setPgPort] = useState(5432);
  const [pgDatabase, setPgDatabase] = useState("");
  const [pgUser, setPgUser] = useState("");
  const [pgPassword, setPgPassword] = useState("");
  const [pgSchemas, setPgSchemas] = useState("public");

  // S3 fields
  const [s3Endpoint, setS3Endpoint] = useState("http://localhost:9000");
  const [s3Bucket, setS3Bucket] = useState("");
  const [s3Prefix, setS3Prefix] = useState("");
  const [s3Region, setS3Region] = useState("us-east-1");
  const [s3UrlStyle, setS3UrlStyle] = useState<"path" | "vhost">("path");
  const [s3AccessKey, setS3AccessKey] = useState("");
  const [s3Secret, setS3Secret] = useState("");

  // Logs fields
  const [logsPath, setLogsPath] = useState("/var/log/myapp/*.log");
  const [logsTableName, setLogsTableName] = useState("");

  // Elasticsearch fields
  const [esUrl, setEsUrl] = useState("http://localhost:9200");
  const [esIndexPattern, setEsIndexPattern] = useState("*");
  const [esUser, setEsUser] = useState("");
  const [esPassword, setEsPassword] = useState("");
  const [esApiKey, setEsApiKey] = useState("");
  const [esVerifyCerts, setEsVerifyCerts] = useState(true);

  // Azure Blob fields
  const [azAccount, setAzAccount] = useState("");
  const [azContainer, setAzContainer] = useState("");
  const [azPrefix, setAzPrefix] = useState("");
  const [azIsAdls, setAzIsAdls] = useState(false);
  const [azAuthMode, setAzAuthMode] = useState<"sas" | "key" | "connstr" | "anon">("sas");
  const [azSasToken, setAzSasToken] = useState("");
  const [azAccountKey, setAzAccountKey] = useState("");
  const [azConnStr, setAzConnStr] = useState("");

  // GCS fields
  const [gcsBucket, setGcsBucket] = useState("");
  const [gcsPrefix, setGcsPrefix] = useState("");
  const [gcsHmacKey, setGcsHmacKey] = useState("");
  const [gcsHmacSecret, setGcsHmacSecret] = useState("");

  // Generic JSON for any custom type
  const [genericJson, setGenericJson] = useState("{\n  \n}");
  const [jsonError, setJsonError] = useState<string | null>(null);

  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const currentTypeMeta = types.find((t) => t.type === type);
  const useGenericForm = !KNOWN_FORMS.has(type);

  function connection(): Record<string, unknown> | null {
    if (type === "postgres") {
      return {
        host: pgHost,
        port: pgPort,
        database: pgDatabase,
        user: pgUser,
        password: pgPassword,
        schemas: pgSchemas.split(",").map((s) => s.trim()).filter(Boolean),
      };
    }
    if (type === "s3") {
      return {
        endpoint: s3Endpoint,
        bucket: s3Bucket,
        prefix: s3Prefix,
        region: s3Region,
        url_style: s3UrlStyle,
        access_key: s3AccessKey,
        secret_access_key: s3Secret,
      };
    }
    if (type === "logs") {
      const conn: Record<string, unknown> = { path: logsPath };
      if (logsTableName.trim()) conn.table_name = logsTableName.trim();
      return conn;
    }
    if (type === "elasticsearch") {
      const conn: Record<string, unknown> = {
        url: esUrl,
        index_pattern: esIndexPattern || "*",
        verify_certs: esVerifyCerts,
      };
      if (esUser.trim()) conn.user = esUser.trim();
      if (esPassword) conn.password = esPassword;
      if (esApiKey) conn.api_key = esApiKey;
      return conn;
    }
    if (type === "azure_blob") {
      const conn: Record<string, unknown> = {
        account_name: azAccount.trim(),
        container: azContainer.trim(),
        prefix: azPrefix,
        adls: azIsAdls,
      };
      if (azAuthMode === "sas" && azSasToken) conn.sas_token = azSasToken;
      if (azAuthMode === "key" && azAccountKey) conn.account_key = azAccountKey;
      if (azAuthMode === "connstr" && azConnStr) conn.connection_string = azConnStr;
      return conn;
    }
    if (type === "gcs") {
      const conn: Record<string, unknown> = {
        bucket: gcsBucket.trim(),
        prefix: gcsPrefix,
      };
      if (gcsHmacKey) conn.hmac_access_key = gcsHmacKey;
      if (gcsHmacSecret) conn.hmac_secret = gcsHmacSecret;
      return conn;
    }
    // Generic JSON form for custom connectors. Parse + validate.
    try {
      const parsed = JSON.parse(genericJson);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        setJsonError("Connection must be a JSON object.");
        return null;
      }
      setJsonError(null);
      return parsed as Record<string, unknown>;
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : "Invalid JSON.");
      return null;
    }
  }

  function readyToSubmit(): boolean {
    if (!name || !type) return false;
    if (type === "postgres") return !!(pgDatabase && pgUser);
    if (type === "s3") return !!s3Bucket;
    if (type === "logs") return !!logsPath.trim();
    if (type === "elasticsearch") return !!esUrl.trim();
    if (type === "azure_blob") return !!(azAccount.trim() && azContainer.trim());
    if (type === "gcs") return !!gcsBucket.trim();
    // Generic — let backend validate.
    return genericJson.trim().length > 2;
  }

  async function onTest() {
    setTest({ kind: "testing" });
    const conn = connection();
    if (!conn) {
      setTest({ kind: "fail", message: jsonError ?? "Invalid connection." });
      return;
    }
    try {
      const r = await testConnection(type, conn);
      setTest(r.ok ? { kind: "ok" } : { kind: "fail", message: r.error ?? "Connection failed" });
    } catch (e) {
      setTest({ kind: "fail", message: e instanceof Error ? e.message : String(e) });
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    const conn = connection();
    if (!conn) {
      setSubmitError(jsonError ?? "Invalid connection.");
      setSubmitting(false);
      return;
    }
    try {
      const s = await createSource({ name, type, connection: conn });
      onCreated(s);
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold">Add data source</h2>
        <button type="button" onClick={onCancel} className="text-xs text-muted hover:text-neutral-200">
          Cancel
        </button>
      </div>

      <Field label="Display name" hint="A friendly name. Used in chat (e.g. demo-shop, marketing-lake).">
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. production-postgres"
          className={inputClass}
        />
      </Field>

      <Field label="Type">
        {typesError && (
          <div className="rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            Could not load connector types: {typesError}
          </div>
        )}
        {!typesError && types.length === 0 && (
          <div className="text-xs text-muted">Loading…</div>
        )}
        {!typesError && types.length > 0 && (
          <>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {types.map((t) => (
                <button
                  key={t.type}
                  type="button"
                  onClick={() => {
                    setType(t.type);
                    setTest({ kind: "idle" });
                  }}
                  className={`rounded-md border px-3 py-2 text-left text-sm transition ${
                    type === t.type
                      ? "border-accent bg-accent/10 text-neutral-100"
                      : "border-border bg-bg text-neutral-300 hover:bg-panel"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{t.display_name}</span>
                    {!t.builtin && (
                      <span className="rounded bg-purple-500/20 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-purple-300">
                        plugin
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    type=<code>{t.type}</code>
                    {t.credential_keys.length > 0 && (
                      <span> · secrets: {t.credential_keys.join(", ")}</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
            <div className="mt-1 text-xs text-muted">
              Custom connectors are picked up from{" "}
              <code>~/.wekams/connectors/</code> and{" "}
              <code>connectors/external/</code>. See WRITING_CONNECTORS.md.
            </div>
          </>
        )}
      </Field>

      {type === "postgres" && (
        <PostgresFields
          host={pgHost} setHost={setPgHost}
          port={pgPort} setPort={setPgPort}
          database={pgDatabase} setDatabase={setPgDatabase}
          user={pgUser} setUser={setPgUser}
          password={pgPassword} setPassword={setPgPassword}
          schemas={pgSchemas} setSchemas={setPgSchemas}
        />
      )}
      {type === "s3" && (
        <S3Fields
          endpoint={s3Endpoint} setEndpoint={setS3Endpoint}
          bucket={s3Bucket} setBucket={setS3Bucket}
          prefix={s3Prefix} setPrefix={setS3Prefix}
          region={s3Region} setRegion={setS3Region}
          urlStyle={s3UrlStyle} setUrlStyle={setS3UrlStyle}
          accessKey={s3AccessKey} setAccessKey={setS3AccessKey}
          secret={s3Secret} setSecret={setS3Secret}
        />
      )}
      {type === "logs" && (
        <LogsFields
          path={logsPath} setPath={setLogsPath}
          tableName={logsTableName} setTableName={setLogsTableName}
        />
      )}
      {type === "elasticsearch" && (
        <ElasticsearchFields
          url={esUrl} setUrl={setEsUrl}
          indexPattern={esIndexPattern} setIndexPattern={setEsIndexPattern}
          user={esUser} setUser={setEsUser}
          password={esPassword} setPassword={setEsPassword}
          apiKey={esApiKey} setApiKey={setEsApiKey}
          verifyCerts={esVerifyCerts} setVerifyCerts={setEsVerifyCerts}
        />
      )}
      {type === "azure_blob" && (
        <AzureBlobFields
          account={azAccount} setAccount={setAzAccount}
          container={azContainer} setContainer={setAzContainer}
          prefix={azPrefix} setPrefix={setAzPrefix}
          isAdls={azIsAdls} setIsAdls={setAzIsAdls}
          authMode={azAuthMode} setAuthMode={setAzAuthMode}
          sasToken={azSasToken} setSasToken={setAzSasToken}
          accountKey={azAccountKey} setAccountKey={setAzAccountKey}
          connStr={azConnStr} setConnStr={setAzConnStr}
        />
      )}
      {type === "gcs" && (
        <GcsFields
          bucket={gcsBucket} setBucket={setGcsBucket}
          prefix={gcsPrefix} setPrefix={setGcsPrefix}
          hmacKey={gcsHmacKey} setHmacKey={setGcsHmacKey}
          hmacSecret={gcsHmacSecret} setHmacSecret={setGcsHmacSecret}
        />
      )}
      {useGenericForm && currentTypeMeta && (
        <GenericConnectionEditor
          meta={currentTypeMeta}
          value={genericJson}
          onChange={(v) => {
            setGenericJson(v);
            setJsonError(null);
          }}
          error={jsonError}
        />
      )}

      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          onClick={onTest}
          disabled={test.kind === "testing" || !readyToSubmit()}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-panel disabled:opacity-50"
        >
          {test.kind === "testing" ? "Testing…" : "Test connection"}
        </button>
        <button
          type="submit"
          disabled={submitting || !readyToSubmit()}
          className="rounded-md bg-accent px-4 py-1.5 text-sm font-medium text-bg disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "Saving…" : "Add source"}
        </button>
        <div className="text-xs">
          {test.kind === "ok" && <span className="text-accent">✓ connection works</span>}
          {test.kind === "fail" && <span className="text-red-400">✗ {test.message}</span>}
        </div>
      </div>

      {submitError && (
        <div className="rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300">
          {submitError}
        </div>
      )}
    </form>
  );
}

// ── Per-type field groups ──────────────────────────────────────────

function PostgresFields(p: {
  host: string; setHost: (v: string) => void;
  port: number; setPort: (v: number) => void;
  database: string; setDatabase: (v: string) => void;
  user: string; setUser: (v: string) => void;
  password: string; setPassword: (v: string) => void;
  schemas: string; setSchemas: (v: string) => void;
}) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Host"><input required value={p.host} onChange={(e) => p.setHost(e.target.value)} className={inputClass} /></Field>
        <Field label="Port"><input type="number" required value={p.port} onChange={(e) => p.setPort(parseInt(e.target.value, 10))} className={inputClass} /></Field>
      </div>
      <Field label="Database"><input required value={p.database} onChange={(e) => p.setDatabase(e.target.value)} placeholder="e.g. shop" className={inputClass} /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="User"><input required value={p.user} onChange={(e) => p.setUser(e.target.value)} className={inputClass} /></Field>
        <Field label="Password" hint="Encrypted at rest in the catalog vault."><input type="password" value={p.password} onChange={(e) => p.setPassword(e.target.value)} className={inputClass} /></Field>
      </div>
      <Field label="Schemas" hint="Comma-separated Postgres schemas to introspect."><input value={p.schemas} onChange={(e) => p.setSchemas(e.target.value)} className={inputClass} /></Field>
    </>
  );
}

function S3Fields(p: {
  endpoint: string; setEndpoint: (v: string) => void;
  bucket: string; setBucket: (v: string) => void;
  prefix: string; setPrefix: (v: string) => void;
  region: string; setRegion: (v: string) => void;
  urlStyle: "path" | "vhost"; setUrlStyle: (v: "path" | "vhost") => void;
  accessKey: string; setAccessKey: (v: string) => void;
  secret: string; setSecret: (v: string) => void;
}) {
  return (
    <>
      <Field label="Endpoint" hint="Leave blank for AWS S3. For MinIO/R2/Wasabi/etc. set the full URL (e.g. http://localhost:9000).">
        <input value={p.endpoint} onChange={(e) => p.setEndpoint(e.target.value)} placeholder="(blank for AWS S3)" className={inputClass} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Bucket"><input required value={p.bucket} onChange={(e) => p.setBucket(e.target.value)} placeholder="e.g. demo-lake" className={inputClass} /></Field>
        <Field label="Prefix" hint="Optional path inside the bucket."><input value={p.prefix} onChange={(e) => p.setPrefix(e.target.value)} placeholder="(blank to scan whole bucket)" className={inputClass} /></Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Region"><input value={p.region} onChange={(e) => p.setRegion(e.target.value)} className={inputClass} /></Field>
        <Field label="URL style" hint="MinIO usually path; AWS S3 usually vhost.">
          <select value={p.urlStyle} onChange={(e) => p.setUrlStyle(e.target.value as "path" | "vhost")} className={inputClass}>
            <option value="path">path</option>
            <option value="vhost">vhost</option>
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Access key"><input value={p.accessKey} onChange={(e) => p.setAccessKey(e.target.value)} placeholder="AKIA…" className={inputClass} /></Field>
        <Field label="Secret access key" hint="Encrypted at rest."><input type="password" value={p.secret} onChange={(e) => p.setSecret(e.target.value)} className={inputClass} /></Field>
      </div>
    </>
  );
}

function LogsFields(p: {
  path: string; setPath: (v: string) => void;
  tableName: string; setTableName: (v: string) => void;
}) {
  return (
    <>
      <Field
        label="Path (glob)"
        hint="One stream per source. Use a glob across files in a directory, e.g. /var/log/myapp/*.log or /tmp/wekams-demo/logs/checkout/*.log. Files must be newline-delimited JSON (one object per line)."
      >
        <input
          required
          value={p.path}
          onChange={(e) => p.setPath(e.target.value)}
          placeholder="/var/log/myapp/*.log"
          className={`${inputClass} font-mono`}
        />
      </Field>
      <Field
        label="Table name (optional)"
        hint="How Lens refers to this stream in chat. Defaults to the parent directory name."
      >
        <input
          value={p.tableName}
          onChange={(e) => p.setTableName(e.target.value)}
          placeholder="(auto)"
          className={inputClass}
        />
      </Field>
    </>
  );
}

function ElasticsearchFields(p: {
  url: string; setUrl: (v: string) => void;
  indexPattern: string; setIndexPattern: (v: string) => void;
  user: string; setUser: (v: string) => void;
  password: string; setPassword: (v: string) => void;
  apiKey: string; setApiKey: (v: string) => void;
  verifyCerts: boolean; setVerifyCerts: (v: boolean) => void;
}) {
  return (
    <>
      <Field
        label="URL"
        hint="The cluster endpoint. http://localhost:9200 for a local OpenSearch / Elasticsearch."
      >
        <input
          required
          value={p.url}
          onChange={(e) => p.setUrl(e.target.value)}
          placeholder="http://localhost:9200"
          className={`${inputClass} font-mono`}
        />
      </Field>
      <Field
        label="Index pattern"
        hint="Glob of indices to expose. Leave as * to introspect every visible non-system index."
      >
        <input
          value={p.indexPattern}
          onChange={(e) => p.setIndexPattern(e.target.value)}
          placeholder="*  or  wekams-*  or  myapp-events"
          className={`${inputClass} font-mono`}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="User (optional)">
          <input
            value={p.user}
            onChange={(e) => p.setUser(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Password (optional)" hint="HTTP basic auth. Encrypted at rest.">
          <input
            type="password"
            value={p.password}
            onChange={(e) => p.setPassword(e.target.value)}
            className={inputClass}
          />
        </Field>
      </div>
      <Field
        label="API key (optional)"
        hint="Sent as Authorization: ApiKey <key>. Encrypted at rest. Leave blank if using basic auth."
      >
        <input
          type="password"
          value={p.apiKey}
          onChange={(e) => p.setApiKey(e.target.value)}
          className={inputClass}
        />
      </Field>
      <label className="flex items-center gap-2 text-sm text-neutral-300">
        <input
          type="checkbox"
          checked={p.verifyCerts}
          onChange={(e) => p.setVerifyCerts(e.target.checked)}
          className="h-4 w-4"
        />
        Verify TLS certificates (uncheck only for trusted self-signed dev clusters)
      </label>
    </>
  );
}

function AzureBlobFields(p: {
  account: string; setAccount: (v: string) => void;
  container: string; setContainer: (v: string) => void;
  prefix: string; setPrefix: (v: string) => void;
  isAdls: boolean; setIsAdls: (v: boolean) => void;
  authMode: "sas" | "key" | "connstr" | "anon"; setAuthMode: (v: "sas" | "key" | "connstr" | "anon") => void;
  sasToken: string; setSasToken: (v: string) => void;
  accountKey: string; setAccountKey: (v: string) => void;
  connStr: string; setConnStr: (v: string) => void;
}) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Storage account" hint="The Azure storage account name.">
          <input required value={p.account} onChange={(e) => p.setAccount(e.target.value)} placeholder="acmestorage" className={inputClass} />
        </Field>
        <Field label="Container">
          <input required value={p.container} onChange={(e) => p.setContainer(e.target.value)} placeholder="data-lake" className={inputClass} />
        </Field>
      </div>
      <Field label="Prefix (optional)" hint="Folder path inside the container, e.g. exports/2026/">
        <input value={p.prefix} onChange={(e) => p.setPrefix(e.target.value)} className={inputClass} />
      </Field>
      <label className="flex items-center gap-2 text-sm text-neutral-300">
        <input type="checkbox" checked={p.isAdls} onChange={(e) => p.setIsAdls(e.target.checked)} className="h-4 w-4" />
        This is an ADLS Gen2 account (hierarchical namespace enabled)
      </label>

      <Field label="Authentication">
        <div className="flex flex-wrap gap-2">
          {(["sas", "key", "connstr", "anon"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => p.setAuthMode(m)}
              className={`rounded-md border px-3 py-1.5 text-xs ${
                p.authMode === m
                  ? "border-accent bg-accent/10 text-neutral-100"
                  : "border-border bg-bg text-neutral-300 hover:bg-panel"
              }`}
            >
              {m === "sas" && "SAS token"}
              {m === "key" && "Account key"}
              {m === "connstr" && "Connection string"}
              {m === "anon" && "Anonymous (public)"}
            </button>
          ))}
        </div>
      </Field>

      {p.authMode === "sas" && (
        <Field label="SAS token" hint="Encrypted at rest. Paste from the Azure portal (the leading ? is fine).">
          <input type="password" value={p.sasToken} onChange={(e) => p.setSasToken(e.target.value)} className={inputClass} />
        </Field>
      )}
      {p.authMode === "key" && (
        <Field label="Account key" hint="Encrypted at rest. Full account access — prefer SAS where possible.">
          <input type="password" value={p.accountKey} onChange={(e) => p.setAccountKey(e.target.value)} className={inputClass} />
        </Field>
      )}
      {p.authMode === "connstr" && (
        <Field label="Connection string" hint="The full Azure connection string. Encrypted at rest.">
          <input type="password" value={p.connStr} onChange={(e) => p.setConnStr(e.target.value)} className={inputClass} />
        </Field>
      )}
    </>
  );
}

function GcsFields(p: {
  bucket: string; setBucket: (v: string) => void;
  prefix: string; setPrefix: (v: string) => void;
  hmacKey: string; setHmacKey: (v: string) => void;
  hmacSecret: string; setHmacSecret: (v: string) => void;
}) {
  return (
    <>
      <Field label="Bucket">
        <input required value={p.bucket} onChange={(e) => p.setBucket(e.target.value)} placeholder="acme-data-lake" className={inputClass} />
      </Field>
      <Field label="Prefix (optional)" hint="Folder path inside the bucket, e.g. exports/2026/">
        <input value={p.prefix} onChange={(e) => p.setPrefix(e.target.value)} className={inputClass} />
      </Field>
      <Field
        label="HMAC access key"
        hint="GCP Console → IAM & Admin → Service Accounts → Keys → Interoperability → New HMAC. Leave blank for public buckets."
      >
        <input value={p.hmacKey} onChange={(e) => p.setHmacKey(e.target.value)} placeholder="GOOG1E…" className={inputClass} />
      </Field>
      <Field label="HMAC secret" hint="Encrypted at rest.">
        <input type="password" value={p.hmacSecret} onChange={(e) => p.setHmacSecret(e.target.value)} className={inputClass} />
      </Field>
    </>
  );
}

function GenericConnectionEditor({
  meta,
  value,
  onChange,
  error,
}: {
  meta: SourceTypeDetail;
  value: string;
  onChange: (v: string) => void;
  error: string | null;
}) {
  return (
    <Field
      label="Connection (JSON)"
      hint={
        meta.credential_keys.length > 0
          ? `Fields encrypted at rest: ${meta.credential_keys.join(", ")}. Other fields stored as plaintext config.`
          : "This connector declares no secret fields. All keys here are stored as plaintext config."
      }
    >
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        rows={8}
        className={`${inputClass} font-mono text-xs`}
        placeholder='{\n  "path": "/path/to/file.db"\n}'
      />
      {error && (
        <div className="mt-1 text-xs text-red-400">{error}</div>
      )}
    </Field>
  );
}

// ── Shared bits ───────────────────────────────────────────────────

const inputClass =
  "w-full rounded-md border border-border bg-bg px-3 py-2 text-sm placeholder:text-muted focus:border-accent focus:outline-none";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs uppercase tracking-wider text-muted">{label}</span>
      {children}
      {hint && <span className="block text-xs text-muted">{hint}</span>}
    </label>
  );
}
