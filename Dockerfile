FROM node:24.12.0-bookworm-slim@sha256:7326fb2dbdce998edd72140946851be64ef4a643e8715e138ca467e8e9d92c99 AS workflow-checker

WORKDIR /checker
COPY .crystra-inputs/contracts/workflow-dsl-2-candidate/package.json \
     .crystra-inputs/contracts/workflow-dsl-2-candidate/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY .crystra-inputs/contracts/workflow-dsl-2-candidate/generated ./generated

FROM ghcr.io/astral-sh/uv:0.11.28@sha256:0f36cb9361a3346885ca3677e3767016687b5a170c1a6b88465ec14aefec90aa AS uv
FROM python:3.14.6-slim-bookworm@sha256:4c92ffcde4dd6f1ff72a24518f49fd4990b27134987dfa31a733badde66df9f8 AS build

WORKDIR /workspace/crystra-evolution
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv build --wheel --python 3.14 && \
    uv venv /opt/venv --python 3.14 && \
    uv pip install --python /opt/venv/bin/python dist/*.whl

FROM python:3.14.6-slim-bookworm@sha256:4c92ffcde4dd6f1ff72a24518f49fd4990b27134987dfa31a733badde66df9f8

ARG CRYSTRA_RELEASE_REVISION=unbound
LABEL org.opencontainers.image.source="https://github.com/firestige/crystra-evolution" \
      org.opencontainers.image.revision=$CRYSTRA_RELEASE_REVISION

WORKDIR /app
COPY --from=workflow-checker /usr/local/bin/node /usr/local/bin/node
COPY --from=workflow-checker /checker /opt/workflow-dsl
COPY --from=build /opt/venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    CRYSTRA_EVOLUTION_CONFIG=/run/config/evolution.json

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).read()" || exit 1
CMD ["python", "-m", "crystra_evolution"]
