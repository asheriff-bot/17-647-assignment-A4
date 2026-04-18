# A4 Book data sync batch (RDS -> MongoDB); run via CronJob, not a long-running service.
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sync.py .
CMD ["python", "sync.py"]
