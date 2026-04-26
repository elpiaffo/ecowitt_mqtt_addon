ARG BUILD_FROM="alpine"
FROM $BUILD_FROM

ENV LANG C.UTF-8

# Python + paho-mqtt + requests + jq direkt aus Alpine
RUN apk add --no-cache python3 py3-paho-mqtt py3-requests jq

COPY ecowitt_mqtt_bridge.py /app/ecowitt_mqtt_bridge.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

SHELL ["/bin/sh", "-c"]
CMD ["/run.sh"]
