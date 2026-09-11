# Grafana Loki. The official image ships only the loki binary itself — no
# shell, curl, or wget — so a compose-level healthcheck (as used for grafana)
# has nothing to exec. busybox's wget is copied in to give it one; the musl
# build is static-pie linked, so it needs no libc from this near-scratch base.
FROM busybox:1.38.0-musl AS busybox

FROM grafana/loki:3.7.7
COPY --from=busybox /bin/busybox /bin/busybox

# /ready reports 503 until the ingester finishes joining the ring and 200
# once Loki can accept writes; start_period covers that window so otel-
# collector's depends_on: condition: service_healthy doesn't start log
# export against a 503.
HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=30s \
    CMD ["/bin/busybox", "wget", "-q", "-O", "/dev/null", "http://localhost:3100/ready"]
