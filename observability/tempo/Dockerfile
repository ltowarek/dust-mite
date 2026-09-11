# Grafana Tempo. The official image ships only the tempo binary itself — no
# shell, curl, or wget — so a compose-level healthcheck (as used for grafana)
# has nothing to exec. busybox's wget is copied in to give it one; the musl
# build is static-pie linked, so it needs no libc from this near-scratch base.
FROM busybox:1.38.0-musl AS busybox

FROM grafana/tempo:3.0.0
COPY --from=busybox /bin/busybox /bin/busybox

# A single instance reports ready almost immediately, no ring to join;
# start_period only covers process startup, matching grafana's own value.
HEALTHCHECK --interval=5s --timeout=3s --retries=10 --start-period=10s \
    CMD ["/bin/busybox", "wget", "-q", "-O", "/dev/null", "http://localhost:3200/ready"]
