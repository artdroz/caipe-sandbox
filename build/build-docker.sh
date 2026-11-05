#!/usr/bin/env bash
set -euo pipefail

image= dockerfile= build_arguments=
while (($#)); do
  case "$1" in
    --image) image="$2"; shift 2 ;;
    --path) dockerfile="$2"; shift 2 ;;
    --args) build_arguments="$2"; shift 2 ;;
    *) echo "Unknown build option: $1" >&2; exit 2 ;;
  esac
done
if [[ -z "$image" || -z "$dockerfile" ]]; then
  echo 'Usage: build-docker.sh --image IMAGE --path DOCKERFILE --args "--platform linux/amd64"' >&2
  exit 2
fi
read -r -a docker_args <<< "$build_arguments"

if [[ "$dockerfile" == images/portal/Dockerfile ]]; then
  audit_id="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$(date -u +%s)"
  for target in browser-audit audit; do
    docker build "${docker_args[@]}" --target "$target" \
      --build-arg "SECURITY_AUDIT_ID=$audit_id" --file "$dockerfile" .
  done
fi
docker build "${docker_args[@]}" --tag "$image" --file "$dockerfile" .

report_dir="$(pwd)/security-reports/${image//[^a-zA-Z0-9._-]/_}"
mkdir -p "$report_dir"
image_id=$(docker image inspect --format '{{.Id}}' "$image")
printf '%s\n' "$image_id" > "$report_dir/image-id.txt"
ignore_file=/dev/null
"$(dirname -- "${BASH_SOURCE[0]}")/scan-image.sh" "$image_id" "$report_dir" "$ignore_file"
test "$(docker image inspect --format '{{.Id}}' "$image")" = "$image_id"
