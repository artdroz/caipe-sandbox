{{- define "agent-sandbox-portal.openshell.env" -}}
- name: PORTAL_OPENSHELL_ENDPOINT
  value: {{ .Values.settings.openShell.endpoint | quote }}
- name: PORTAL_OPENSHELL_GATEWAY_ID
  value: {{ .Values.settings.openShell.gatewayId | quote }}
- name: PORTAL_OPENSHELL_GATEWAY_SERVICE_ACCOUNT
  value: {{ .Values.settings.openShell.gatewayServiceAccount | quote }}
- name: PORTAL_OPENSHELL_RUNNER_SERVICE_ACCOUNT
  value: {{ .Values.settings.openShell.sandboxServiceAccount | quote }}
- name: PORTAL_OPENSHELL_STORAGE_GIB
  value: {{ .Values.settings.openShell.storageGiB | quote }}
- name: PORTAL_OPENSHELL_SUPERVISOR_RESOURCES
  value: {{ .Values.settings.openShell.supervisorResources | toJson | quote }}
- name: PORTAL_OPENSHELL_GATEWAY_POD_SELECTOR
  value: {{ .Values.settings.openShell.gatewayPodSelector | toJson | quote }}
- name: PORTAL_OPENSHELL_NAMESPACE_LABEL
  value: {{ .Values.settings.openShell.namespaceLabel | quote }}
{{- end -}}

{{- define "agent-sandbox-portal.openshell.mounts" -}}
{{- if .Values.settings.openShell.endpoint }}
- name: openshell-client
  mountPath: /etc/portal-openshell
  readOnly: true
{{- end }}
{{- end -}}

{{- define "agent-sandbox-portal.openshell.volumes" -}}
{{- if .Values.settings.openShell.endpoint }}
- name: openshell-client
  secret:
    secretName: {{ required "settings.openShell.clientSecret is required" .Values.settings.openShell.clientSecret }}
    defaultMode: 0440
    items:
      - {key: ca.crt, path: ca.crt}
      - {key: tls.crt, path: tls.crt}
      - {key: tls.key, path: tls.key}
{{- end }}
{{- end -}}

{{- define "agent-sandbox-portal.openshell.bindings" -}}
{{- $base := printf "%s-%s" .Release.Namespace .Release.Name | trunc 48 | trimSuffix "-" }}
{{- if .Values.settings.openShell.endpoint }}
|| (object.metadata.name == 'sandbox-openshell-access'
  && object.roleRef.kind == 'ClusterRole'
  && object.roleRef.name == '{{ $base }}-access-openshell'
  && namespaceObject.metadata.labels['sandbox.caipe.io/backend'] == 'openShell'
  && object.subjects.size() == 1
  && object.subjects[0].kind == 'ServiceAccount'
  && object.subjects[0].name == '{{ .Values.settings.openShell.gatewayServiceAccount }}'
  && object.subjects[0].namespace == '{{ .Release.Namespace }}')
{{- end }}
{{- end -}}

{{- define "agent-sandbox-portal.openshell.runnerIdentities" -}}
{{- if .Values.settings.openShell.endpoint }}, '{{ .Values.settings.openShell.sandboxServiceAccount }}'{{ end -}}
{{- end -}}

{{- define "agent-sandbox-portal.openshell.accessRoles" -}}
{{- $base := printf "%s-%s" .Release.Namespace .Release.Name | trunc 48 | trimSuffix "-" }}
{{- if .Values.settings.openShell.endpoint }}, {{ $base }}-access-openshell{{ end -}}
{{- end -}}
{{- define "agent-sandbox-portal.openshell.networkPolicySelector" -}}
|| (has(namespaceObject.metadata.labels)
    && 'sandbox.caipe.io/backend' in namespaceObject.metadata.labels
    && namespaceObject.metadata.labels['sandbox.caipe.io/backend'] == 'openShell'
    && has(object.spec.podSelector.matchLabels)
    && object.spec.podSelector.matchLabels.size() == 1
    && object.spec.podSelector.matchLabels['openshell.ai/component'] == 'supervisor'
    && (!has(object.spec.podSelector.matchExpressions) || object.spec.podSelector.matchExpressions.size() == 0))
{{- end -}}
