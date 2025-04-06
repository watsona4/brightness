FROM ghcr.io/watsona4/python-pvlib:latest

RUN apk update && apk add --no-cache mosquitto-clients

ENV HDF5_DISABLE_VERSION_CHECK=1

COPY brightness.py healthcheck.sh ./

HEALTHCHECK CMD ./healthcheck.sh

LABEL org.opencontainers.image.source=https://github.com/watsona4/brightness

CMD ["python", "brightness.py"]
