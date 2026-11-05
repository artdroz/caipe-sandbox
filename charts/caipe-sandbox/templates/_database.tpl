{{- define "agent-sandbox-portal.database.command" -}}
{{- $action := ternary "migrate" "check" (eq .Values.strategy.type "Recreate") -}}
{{- list "python" "-m" "portal.storage" $action | toJson -}}
{{- end }}

{{- define "agent-sandbox-portal.database.env" -}}
- name: PORTAL_DATABASE_URL
  {{- if .Values.database.existingSecret }}
  valueFrom:
    secretKeyRef:
      name: {{ .Values.database.existingSecret | quote }}
      key: {{ .Values.database.secretKey | quote }}
  {{- else }}
  value: {{ .Values.database.url | quote }}
  {{- end }}
- name: PORTAL_DATABASE_BACKEND
  value: {{ ternary "postgresql" "sqlite" (not (empty .Values.database.existingSecret)) | quote }}
{{- end }}

{{- define "agent-sandbox-portal.database.mounts" -}}
{{- if not .Values.database.existingSecret }}
- name: metadata
  mountPath: /var/lib/portal
{{- end }}
{{- if .Values.database.caSecret }}
- name: database-ca
  mountPath: /etc/portal-database
  readOnly: true
{{- end }}
{{- end }}

{{- define "agent-sandbox-portal.database.volumes" -}}
{{- if not .Values.database.existingSecret }}
- name: metadata
  persistentVolumeClaim:
    claimName: {{ .Release.Name }}-metadata
{{- end }}
{{- if .Values.database.caSecret }}
- name: database-ca
  secret:
    secretName: {{ .Values.database.caSecret | quote }}
    items:
      - key: ca.crt
        path: ca.crt
{{- end }}
{{- end }}
