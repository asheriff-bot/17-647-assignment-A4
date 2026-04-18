# A2 Mobile BFF: port 80; GET /status, /customers*, /books* (forward + transform); JWT required. Build from repo root.
FROM python:3.11-slim
WORKDIR /app
COPY mobile_bff/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared ./shared
COPY mobile_bff/app.py .
ENV PORT=80
EXPOSE 80
CMD ["python", "app.py"]
