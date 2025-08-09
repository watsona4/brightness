FROM ghcr.io/watsona4/python-pvlib:latest

RUN apk update && apk add --no-cache mosquitto-clients

ENV HDF5_DISABLE_VERSION_CHECK=1

COPY brightness.py healthcheck.py ./

RUN chmod +x healthcheck.py

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD /usr/bin/python3 /healthcheck.py

LABEL org.opencontainers.image.source=https://github.com/watsona4/brightness

CMD ["python", "brightness.py"]
