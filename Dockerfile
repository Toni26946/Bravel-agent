FROM python:3.11-slim

# Bez bufferiranja stdout/stderr -> logovi odmah vidljivi u `fly logs`.
# (fly.toml [processes] override-a CMD "python -u", pa ENV osigurava
#  unbuffered ispis neovisno o tome kojom se komandom pokrece.)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "main.py"]
