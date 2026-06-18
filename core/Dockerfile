FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    gspread \
    google-auth \
    requests \
    python-dotenv \
    Pillow

COPY main.py .

CMD ["python", "main.py"]
