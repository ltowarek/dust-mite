# Grafana Pyroscope. The official image ships only the pyroscope binary
# itself — no shell, curl, or wget — so a compose-level healthcheck (as used
# for grafana) has nothing to exec. busybox's wget is copied in to give it
# one; the musl build is static-pie linked, so it needs no libc from this
# near-scratch base.
FROM busybox:1.38.0-musl AS busybox

FROM grafana/pyroscope:2.1.1
COPY --from=busybox /bin/busybox /bin/busybox

# /ready gates on the metastore, then the ingester, then the segment writer
# in turn, each with its own settle delay after its own dependencies are
# met; start_period covers the full chain, not just the first component.
HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=45s \
    CMD ["/bin/busybox", "wget", "-q", "-O", "/dev/null", "http://localhost:4040/ready"]
