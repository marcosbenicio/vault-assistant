FROM python:3.12.13-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
# torch first, from pytorch's CPU wheel index: the default PyPI torch
# ships the whole CUDA runtime (~2.5 GB) that this container never
# uses - embeddings run on cpu here, and gpu inference belongs to the
# ollama service. Cuts the image by gigabytes and the first build by
# minutes. Same pinned version as the measured environment, cpu flavor.
RUN pip install --no-cache-dir torch==2.13.0+cpu \
      --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

COPY assistant/ ./

EXPOSE 8501

CMD ["streamlit", "run", "app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true"]
