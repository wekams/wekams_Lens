{{/*
Common helpers.
*/}}

{{- define "wekams-lens.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "wekams-lens.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "wekams-lens.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "wekams-lens.labels" -}}
helm.sh/chart: {{ include "wekams-lens.chart" . }}
{{ include "wekams-lens.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{- define "wekams-lens.selectorLabels" -}}
app.kubernetes.io/name: {{ include "wekams-lens.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "wekams-lens.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "wekams-lens.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Catalog DB URL — either user-supplied (external mode) or the in-cluster
StatefulSet (bundled mode).
*/}}
{{- define "wekams-lens.catalogDbUrl" -}}
{{- if eq .Values.postgres.mode "bundled" -}}
postgresql+asyncpg://wekams:wekams@{{ include "wekams-lens.fullname" . }}-postgres:5432/wekams_catalog
{{- else -}}
{{ .Values.postgres.url }}
{{- end -}}
{{- end }}
