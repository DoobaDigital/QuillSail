FROM python:3.15-slim-bookworm AS builder
WORKDIR /build
COPY . .
RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels '.[server,postgres,mysql]'

FROM python:3.15-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    COPYDESK_CONFIG=/var/lib/copydesk/copydesk.toml
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels 'copydesk[server,postgres,mysql]' \
    && rm -rf /wheels \
    && mkdir -p /var/lib/copydesk \
    && chown 10001:10001 /var/lib/copydesk
COPY deploy/container /app/container
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "/app/container/healthcheck.py", "web"]
ENTRYPOINT ["python", "/app/container/entrypoint.py"]
CMD ["web"]
LABEL org.opencontainers.image.title="QuillSail" \
      org.opencontainers.image.description="Self-hosted blogs, community publishing and newsletters" \
      org.opencontainers.image.licenses="MIT"
