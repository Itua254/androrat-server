FROM python:3.11-slim

WORKDIR /app

# Copy the server code
COPY server.py .
COPY requirements.txt .

# Install dependencies (none currently, but future-proof)
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port (Railway overrides this with $PORT)
EXPOSE 8000

# Run the server
CMD ["python", "server.py"]

