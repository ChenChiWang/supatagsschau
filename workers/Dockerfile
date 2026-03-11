FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends git openssh-client ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Git commit 用的身份設定
RUN git config --global user.name "tagesschau-bot" && \
    git config --global user.email "bot@supatagesschau.jwais.com"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
