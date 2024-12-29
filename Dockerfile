# Use an official Python runtime as a parent image
FROM python:3-slim AS base-image
RUN apt-get update
RUN apt-get install -y --no-install-recommends libglib2.0-dev bluez bluetooth libbluetooth-dev
RUN python3 -m venv /venv

FROM base-image AS build-image
# keep the build dependencies in a build specific image
RUN apt-get install -y --no-install-recommends build-essential git
WORKDIR /app
COPY requirements.txt /app/
# Install any needed packages specified in requirements.txt 
RUN /venv/bin/pip install --no-cache-dir --requirement /app/requirements.txt


FROM base-image AS runtime-image
WORKDIR /app
COPY --from=build-image /venv /venv
COPY ./bledist/ /app/bledist/
COPY ./config/ /app/config/
COPY ./augustpy/ /app/augustpy/
COPY ./mqtt_august_bridge.py /app/

CMD ["/venv/bin/python3", "/app/mqtt_august_bridge.py"]
