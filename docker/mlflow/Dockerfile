FROM python:3.12.8-slim

RUN python -m pip install --no-cache-dir \
    boto3==1.35.99 \
    mlflow==2.17.2 \
    psycopg2-binary==2.9.10 \
    && groupadd --gid 10001 mlflow \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin mlflow \
    && mkdir -p /home/mlflow/.mlflow \
    && chown -R 10001:10001 /home/mlflow

USER 10001:10001

EXPOSE 5000
