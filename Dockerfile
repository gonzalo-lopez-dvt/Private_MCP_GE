FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run inyecta $PORT (por defecto 8080). server.py lo lee de la env.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
