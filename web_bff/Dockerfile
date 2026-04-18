# A2 Web BFF: port 80; GET /status, /customers*, /books* (forward to backend); JWT required. Build from repo root.
FROM python:3.11-slim
WORKDIR /app
COPY web_bff/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared ./shared
COPY web_bff/app.py .
ENV PORT=80
EXPOSE 80
CMD ["python", "app.py"]
