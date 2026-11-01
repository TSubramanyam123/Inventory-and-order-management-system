FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common common
COPY services services
COPY scripts scripts
COPY tests tests
COPY pytest.ini .
RUN useradd -m app && mkdir /data && chown app:app /data
USER app
ENV DATA_DIR=/data
ARG SERVICE_NAME=cart
ENV SERVICE_NAME=${SERVICE_NAME}
CMD ["sh", "-c", "exec uvicorn services.${SERVICE_NAME}:app --host 0.0.0.0 --port 8000"]
