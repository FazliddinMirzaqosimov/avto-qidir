# EV Hunter — the scanner uses the Python standard library only, so there is nothing
# to install and no build stage to speak of.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ev-hunter" \
      org.opencontainers.image.description="Hourly EV deal scanner for Uzbek marketplaces" \
      org.opencontainers.image.source="https://github.com/FazliddinMirzaqosimov/avto-qidir"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tashkent \
    EV_HUNTER_DATA_DIR=/data

# tzdata so container timestamps match Tashkent; ca-certificates for the HTTPS scrapes.
# curl is not a convenience here — it is the HTTP/2 transport. OLX's CloudFront WAF
# answers every HTTP/1.1 request with 403, and Python's urllib cannot speak HTTP/2, so
# without curl in the image the largest source returns nothing at all.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* \
 && curl --version | head -1

# Unprivileged runtime user. /data is created here so a fresh named volume inherits
# this ownership when Docker seeds it.
RUN useradd --system --uid 10001 --create-home --home-dir /home/evhunter evhunter \
 && mkdir -p /data \
 && chown -R evhunter:evhunter /data

WORKDIR /app
COPY app/ /app/
RUN chmod +x /app/entrypoint.sh && chown -R evhunter:evhunter /app

USER evhunter
VOLUME ["/data"]

HEALTHCHECK --interval=10m --timeout=20s --start-period=20m --retries=3 \
    CMD ["python", "/app/healthcheck.py"]

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["service"]
