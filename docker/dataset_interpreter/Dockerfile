FROM python:3.13-slim-bookworm

RUN pip install --no-cache-dir "numpy==2.5.2" "pandas==3.0.5"

WORKDIR /opt/hv-interpreter
COPY healthcheck.py runner.py server.py ./

ENV HV_DATASET_INTERPRETER_SOCKET=/run/hv-dataset-interpreter/interpreter.sock \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=10s --timeout=2s --start-period=5s --retries=5 \
    CMD ["python", "-I", "/opt/hv-interpreter/healthcheck.py"]

CMD ["python", "-I", "/opt/hv-interpreter/server.py"]
