FROM ghcr.io/watsona4/python-pvlib:latest

ENV HDF5_DISABLE_VERSION_CHECK=1

COPY brightness.py .

LABEL org.opencontainers.image.source=https://github.com/watsona4/brightness

CMD ["python", "brightness.py"]
