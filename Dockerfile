FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HCR2_HOST=0.0.0.0 \
    HCR2_PORT=8311 \
    HCR2_DATA_DIR=/var/lib/hcr2/player_data \
    HCR2_DECRYPTED_DIR=/opt/hcr2/config \
    HCR2_SO_PATH=/opt/hcr2/lib/libcocos2dcpp.so

WORKDIR /opt/hcr2/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN mkdir -p /var/lib/hcr2/player_data /opt/hcr2/config /opt/hcr2/lib \
    && useradd --system --uid 10001 --create-home hcr2 \
    && chown -R hcr2:hcr2 /var/lib/hcr2 /opt/hcr2
USER hcr2

EXPOSE 8311/tcp
VOLUME ["/var/lib/hcr2", "/opt/hcr2/config", "/opt/hcr2/lib"]
CMD ["python", "run_server.py", "--host", "0.0.0.0", "--port", "8311"]
