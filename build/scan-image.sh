#!/usr/bin/env bash
set -euo pipefail

image_id=${1:?An immutable image ID is required}
report_dir=${2:?A report directory is required}
ignore_file=${3:-/dev/null}
# Verify signatures and review release provenance before changing this digest.
scanner_image=ghcr.io/aquasecurity/trivy@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c # Trivy v0.76.1
helper_image=python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 # Python 3.12 slim
temporary=$(mktemp -d)
volume_prefix="sandbox-scan-${temporary##*/}"
input_volume="$volume_prefix-input"
cache_volume="$volume_prefix-cache"
helper=
mkdir -p "$report_dir"

cleanup() {
  local result=$?
  trap - EXIT
  if [[ -n "$helper" ]]; then
    if ! docker cp "$helper:/cache/reports/." "$report_dir"; then
      if ((result == 0)); then result=1; fi
    fi
    docker cp "$helper:/cache/db/metadata.json" "$report_dir/db-metadata.json" 2>/dev/null || true
    docker rm --force "$helper" >/dev/null 2>&1 || true
  fi
  docker volume rm "$input_volume" "$cache_volume" >/dev/null 2>&1 || true
  rm -rf "$temporary"
  exit "$result"
}
trap cleanup EXIT

docker pull "$scanner_image"
docker volume create "$input_volume" >/dev/null
docker volume create "$cache_volume" >/dev/null
# Named volumes work with ARC's remote Docker daemon without host bind mounts.
helper=$(docker create --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --mount "type=volume,source=$input_volume,target=/input" \
  --mount "type=volume,source=$cache_volume,target=/cache" \
  --entrypoint /bin/sh "$helper_image" -eu -c \
  'mkdir -p /cache/tmp /cache/reports; chmod 1777 /cache /cache/tmp /cache/reports')
docker image save --output "$temporary/image.tar" "$image_id"
chmod 0444 "$temporary/image.tar"
docker cp "$temporary/image.tar" "$helper:/input/image.tar"
scanner_ignore=/dev/null
if [[ "$ignore_file" != /dev/null ]]; then
  test -s "$ignore_file"
  cp "$ignore_file" "$temporary/accepted-vendor-risks.yaml"
  chmod 0444 "$temporary/accepted-vendor-risks.yaml"
  docker cp "$temporary/accepted-vendor-risks.yaml" "$helper:/input/accepted-vendor-risks.yaml"
  scanner_ignore=/input/accepted-vendor-risks.yaml
fi
docker start --attach "$helper"
test "$(docker inspect --format '{{.State.ExitCode}}' "$helper")" = 0

sandbox=(--rm --user 65532:65532 --read-only --cap-drop ALL
  --security-opt no-new-privileges:true --pids-limit 256 --memory 2g --cpus 2
  --workdir /tmp --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m
  --env TMPDIR=/cache/tmp
  --env HTTP_PROXY= --env HTTPS_PROXY= --env ALL_PROXY= --env NO_PROXY=
  --env http_proxy= --env https_proxy= --env all_proxy= --env no_proxy=
  --mount "type=volume,source=$cache_volume,target=/cache"
  --entrypoint trivy)
scanner=(--config /dev/null --cache-dir /cache --timeout 20m)

# Only the empty database cache is visible while network access is enabled.
docker run "${sandbox[@]}" --network bridge "$scanner_image" "${scanner[@]}" \
  image --download-db-only --db-repository ghcr.io/aquasecurity/trivy-db:2 --skip-version-check
docker run "${sandbox[@]}" --network bridge "$scanner_image" "${scanner[@]}" \
  image --download-java-db-only --java-db-repository ghcr.io/aquasecurity/trivy-java-db:1 --skip-version-check

offline=("${sandbox[@]}" --network none)
scan=(image --input /input/image.tar --offline-scan --skip-db-update
  --skip-java-db-update --skip-version-check --scanners vuln --ignorefile "$scanner_ignore")
result=0
docker run "${offline[@]}" --mount "type=volume,source=$input_volume,target=/input,readonly" \
  "$scanner_image" "${scanner[@]}" "${scan[@]}" --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 \
  --show-suppressed --list-all-pkgs --format json --output /cache/reports/image.trivy.json || result=$?
offline+=("$scanner_image" "${scanner[@]}" convert --ignorefile /dev/null)
docker run "${offline[@]}" --format cyclonedx --output /cache/reports/image.cdx.json /cache/reports/image.trivy.json
docker run "${offline[@]}" --format table --show-suppressed /cache/reports/image.trivy.json
exit "$result"
