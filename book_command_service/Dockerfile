# A4 Book command: RDS writes; POST /cmd/books, PUT /cmd/books/{ISBN}
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
ENV PORT=3000
EXPOSE 3000
CMD ["python", "app.py"]
