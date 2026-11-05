# syntax=docker/dockerfile:1.7
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
LABEL org.opencontainers.image.source="https://github.com/caipe-io/caipe-sandbox" \
      org.opencontainers.image.title="CAIPE Sandbox default tools"
RUN apt-get update && apt-get upgrade -y \
 && apt-get install -y --no-install-recommends bash ca-certificates curl git jq less openssh-client \
 && rm -rf /var/lib/apt/lists/*
COPY sandbox-images/common-tools/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt \
 && useradd --uid 1000 --create-home --shell /bin/bash sandbox
COPY sandbox-images/common-tools/sandbox/ /usr/local/lib/sandbox/
RUN printf '#!/bin/sh\nexec python /usr/local/lib/sandbox/runtime.py start "$@"\n' > /usr/local/bin/sandbox-start \
 && printf '#!/bin/sh\nexec python /usr/local/lib/sandbox/runtime.py control "$@"\n' > /usr/local/bin/sandbox-control \
 && chmod 0555 /usr/local/bin/sandbox-start /usr/local/bin/sandbox-control
ENV HOME=/home/sandbox
WORKDIR /home/sandbox
USER 1000
CMD ["sandbox-start"]
