# sauce.ai/phenotype API image (Railway / any container host).
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["sh","-c","uvicorn app.main:get_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
