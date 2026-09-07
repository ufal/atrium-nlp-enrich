# syntax=docker/dockerfile:1.7
FROM python:3.11-slim AS base

ARG ATRIUM_RUNNER_IMAGE=""
ARG ATRIUM_RUNNER_REPO="https://github.com/ufal/atrium-nlp-enrich"
ARG ATRIUM_RUNNER_REF=""

ENV ATRIUM_RUNNER_IMAGE=${ATRIUM_RUNNER_IMAGE} \
    ATRIUM_RUNNER_REPO=${ATRIUM_RUNNER_REPO} \
    ATRIUM_RUNNER_REF=${ATRIUM_RUNNER_REF} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-test.txt ./
RUN pip install -r requirements.txt -r requirements-test.txt

COPY . .

RUN chmod +x api_1_manifest.sh api_2_udp.sh api_3_nt.sh api_4_stats.sh \
    && useradd --create-home --uid 10001 atrium \
    && mkdir -p /cache/huggingface /data \
    && chown -R atrium:atrium /app /cache /data

USER atrium

ENTRYPOINT ["python", "run_pipeline.py"]
CMD []


# ---------------------------------------------------------------------------
# API surface — published as :<version>-api
# ---------------------------------------------------------------------------
FROM base AS api

USER root
COPY service/requirements.txt ./service_requirements.txt
RUN pip install -r service_requirements.txt
RUN chown -R atrium:atrium /app
USER atrium

EXPOSE 8000
# STOPSIGNAL is the default (SIGTERM) — declared explicitly so it is never silently
# changed by a future edit; service/api.py's lifespan (via serve_lifecycle,
# service/atrium_service.py) chains to uvicorn's own handler for it (issue #55).
STOPSIGNAL SIGTERM
# --timeout-graceful-shutdown bounds uvicorn's own wait for in-flight HTTP requests
# (20s here; nlp-enrich's own background /jobs queue is a SEPARATE mechanism — see
# service/api.py's ServiceState.track() — not covered by this flag at all, since a
# job-submission request already returned before the job finishes). --start-period
# on HEALTHCHECK below covers first-run model downloads; see docs/docker_gha.md §3.4
# and docs/k8s_deployment.md for the full grace-period budget this is sized against.
ENTRYPOINT ["uvicorn", "service.api:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "/app/service/healthcheck.py"]


# ---------------------------------------------------------------------------
# Optional LLM/GPU variant — published as :<version>-llm
# ---------------------------------------------------------------------------
FROM base AS llm

USER root
COPY requirements_llm.txt ./

# Dynamically remove the strict torch==2.7.0 pin so vllm can install its required version
RUN sed -i '/^torch==/d' requirements_llm.txt \
    && pip install \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements_llm.txt

RUN chown -R atrium:atrium /app
USER atrium

ENTRYPOINT ["python", "llm_run.py"]
CMD ["llm_config.txt"]