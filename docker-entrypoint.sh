#!/bin/sh
# Copyright 2026 Query Farm LLC - https://query.farm
#
# Dispatch the vgi-libpostal image into one of its transports:
#   http   (default) HTTP server on $PORT (vgi-serve --http: /health + VGI RPC)
#   stdio            a worker DuckDB spawns over stdio (on-host execution)
#   *                exec'd verbatim (debug escape hatch)
#
# libpostal loads its ~2 GB models lazily on the first parse/expand query; the
# HTTP /health endpoint answers immediately, before the model is resident.
set -e
case "${1:-http}" in
  http)
    shift 2>/dev/null || true
    exec vgi-serve vgi_libpostal.worker:LibpostalWorker --http --host 0.0.0.0 --port "${PORT:-8000}" "$@"
    ;;
  stdio)
    shift 2>/dev/null || true
    exec vgi-libpostal-worker "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
