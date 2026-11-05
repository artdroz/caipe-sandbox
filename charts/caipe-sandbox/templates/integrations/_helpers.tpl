{{/* Explicit registration of installed native integrations. */}}
{{- define "agent-sandbox-portal.integrations.env" -}}
{{- include "agent-sandbox-portal.openshell.env" . -}}
{{- end -}}

{{- define "agent-sandbox-portal.integrations.mounts" -}}
{{- include "agent-sandbox-portal.openshell.mounts" . -}}
{{- end -}}

{{- define "agent-sandbox-portal.integrations.volumes" -}}
{{- include "agent-sandbox-portal.openshell.volumes" . -}}
{{- end -}}

{{- define "agent-sandbox-portal.integrations.bindings" -}}
{{- include "agent-sandbox-portal.openshell.bindings" . -}}
{{- end -}}

{{- define "agent-sandbox-portal.integrations.runnerIdentities" -}}
{{- include "agent-sandbox-portal.openshell.runnerIdentities" . -}}
{{- end -}}

{{- define "agent-sandbox-portal.integrations.accessRoles" -}}
{{- include "agent-sandbox-portal.openshell.accessRoles" . -}}
{{- end -}}

{{- define "agent-sandbox-portal.integrations.backendKeys" -}}
["openShell"]
{{- end -}}
{{- define "agent-sandbox-portal.integrations.networkPolicySelectors" -}}
{{- include "agent-sandbox-portal.openshell.networkPolicySelector" . -}}
{{- end -}}
