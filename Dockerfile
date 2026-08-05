FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY demo_generator/ demo_generator/

EXPOSE 8090

ENTRYPOINT ["python", "-m", "demo_generator.worker.service"]
