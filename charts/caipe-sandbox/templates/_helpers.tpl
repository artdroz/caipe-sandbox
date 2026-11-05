{{- define "agent-sandbox-portal.runtimeClasses" -}}
{{- $classes := .Values.settings.allowedRuntimeClasses -}}
{{- if eq ($classes | toJson) "null" -}}
{{- if not .Values.settings.runtimeClass -}}
{{- fail "explicitly set settings.allowedRuntimeClasses to [\"\"] to approve an empty runtimeClass" -}}
{{- end -}}
{{- $classes = list .Values.settings.runtimeClass -}}
{{- end -}}
{{- if not (has .Values.settings.runtimeClass $classes) -}}
{{- fail "settings.allowedRuntimeClasses must include settings.runtimeClass" -}}
{{- end -}}
{{- $classes | toJson -}}
{{- end -}}
