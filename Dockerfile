FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python -m barndo init
ENV BARNDO_DATA_DIR=/app/data BARNDO_OUTPUT_DIR=/app/output
EXPOSE 8000
CMD ["python", "-m", "barndo", "serve", "--host", "0.0.0.0", "--port", "8000"]
