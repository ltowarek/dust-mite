# Grafana Mimir. The official image ships only the mimir binary itself — no
# shell, curl, or wget — so a compose-level healthcheck (as used for grafana)
# has nothing to exec. busybox's wget is copied in to give it one; the musl
# build is static-pie linked, so it needs no libc from this near-scratch base.
FROM busybox:1.38.0-musl AS busybox

FROM grafana/mimir:3.2.0
COPY --from=busybox /bin/busybox /bin/busybox

# /ready reports 503 until the ingester/store-gateway/compactor rings settle;
# start_period covers that window.
HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=15s \
    CMD ["/bin/busybox", "wget", "-q", "-O", "/dev/null", "http://localhost:8080/ready"]
