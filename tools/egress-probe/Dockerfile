# Throwaway. Delete this directory once the egress question is settled.
# Deliberately dependency-free: the probe is stdlib sockets only, so this image
# proves nothing about the app's package availability, only about the network.
FROM python:3.11-slim
WORKDIR /probe
COPY probe.py .
ENTRYPOINT ["python", "-u", "probe.py"]
