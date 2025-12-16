FROM ghcr.io/watsona4/python-pvlib:latest

RUN apk update && apk add --no-cache mosquitto-clients

ENV HDF5_DISABLE_VERSION_CHECK=1

COPY brightness.py healthcheck.py ./

RUN chmod +x healthcheck.py

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD test -f /tmp/last_publish && [ $(( $(date +%s) - $(cat /tmp/last_publish) )) -lt 180 ]

LABEL org.opencontainers.image.source=https://github.com/watsona4/brightness

CMD ["python", "brightness.py"]
