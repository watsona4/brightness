FROM ghcr.io/watsona4/python-pvlib:latest

ENV TZ="America/New_York"
RUN cp /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY brightness.py .

ENV HDF5_DISABLE_VERSION_CHECK=1

LABEL org.opencontainers.image.source=https://github.com/watsona4/brightness

CMD ["python", "brightness.py"]
