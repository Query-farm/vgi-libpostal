# Copyright 2026 Query Farm LLC - https://query.farm
#
# Single image serving BOTH transports of the vgi-libpostal worker:
#   docker run ... IMG            -> HTTP server on $PORT (default 8000; /health, VGI RPC)
#   docker run -i ... IMG stdio   -> stdio worker DuckDB spawns on-host
# See docker-entrypoint.sh.
#
# THE heavy part: libpostal is NOT pip-installable. The `postal` (pypostal)
# Python binding is a C extension compiled against the libpostal C library, and
# libpostal needs its ~2 GB of statistical data models. So this image builds
# libpostal from source and downloads its data at build time, then compiles
# pypostal against it. The result is a large (~2.5 GB) but fully self-contained
# image: no model download at first query, no native deps to provision on-host.
# syntax=docker/dockerfile:1
FROM python:3.13-slim

ARG VERSION=0.0.0
ARG GIT_COMMIT=unknown
ARG SOURCE_URL=https://github.com/Query-farm/vgi-libpostal
# Pin the libpostal source revision for reproducible builds (master is fine too).
ARG LIBPOSTAL_REF=master

LABEL org.opencontainers.image.title="vgi-libpostal" \
      org.opencontainers.image.description="International address parsing + normalization (libpostal) for DuckDB via VGI (stdio + HTTP)" \
      org.opencontainers.image.source="${SOURCE_URL}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.licenses="MIT" \
      farm.query.vgi.transports='["http","stdio"]'

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    LIBPOSTAL_PREFIX=/usr/local \
    LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app

# Build libpostal from source (+ download its ~2 GB data models). The C toolchain
# (build-essential / autotools) is KEPT in the image on purpose: the `postal`
# (pypostal) Python binding is a C extension that compiles against libpostal at
# `pip install` time (below), so gcc must still be present then. curl also backs
# the HEALTHCHECK / CI /health smoke. On non-x86_64 (e.g. arm64) libpostal's SSE2
# path is unavailable, so configure with --disable-sse2 there; x86_64 keeps the
# SSE2-optimized build.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        curl ca-certificates git build-essential autoconf automake libtool pkg-config; \
    git clone --depth 1 --branch "${LIBPOSTAL_REF}" https://github.com/openvenues/libpostal /tmp/libpostal; \
    cd /tmp/libpostal; \
    ./bootstrap.sh; \
    SSE_FLAG=""; \
    case "$(uname -m)" in x86_64|amd64) : ;; *) SSE_FLAG="--disable-sse2" ;; esac; \
    ./configure --prefix="${LIBPOSTAL_PREFIX}" --datadir="${LIBPOSTAL_PREFIX}/share/libpostal" ${SSE_FLAG}; \
    make -j"$(nproc)"; \
    make install; \
    ldconfig; \
    cd /; \
    rm -rf /tmp/libpostal; \
    rm -rf /var/lib/apt/lists/*

# Install the worker + HTTP-serving extra. pypostal's C extension compiles
# against the libpostal we just built (headers in /usr/local/include, lib in
# /usr/local/lib) using the toolchain kept in the layer above.
COPY pyproject.toml README.md LICENSE ./
COPY vgi_libpostal ./vgi_libpostal
RUN CFLAGS="-I${LIBPOSTAL_PREFIX}/include" LDFLAGS="-L${LIBPOSTAL_PREFIX}/lib" \
    pip install '.[serve]'

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -fsS "http://localhost:${PORT}/health" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["http"]
