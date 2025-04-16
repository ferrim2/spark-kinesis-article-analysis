FROM apache/spark:3.5.5

USER root
RUN mkdir -p /opt/spark/checkpoints && \
    chown -R spark:spark /opt/spark/checkpoints
USER spark