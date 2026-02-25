# MultiHost Keeper

Multi-platform auto-renew and keepalive manager with optional proxy support.

## Quick start (Docker Compose)

Create `docker-compose.yml` in the directory you want to persist data in, then run `docker compose up -d`.

```yml
services:
  multihost-keeper:
    image: ghcr.io/debbide/multihost-keeper:latest
    container_name: multihost-keeper
    restart: unless-stopped
    ports:
      - "5000:5000"
    volumes:
      # Persist data in the same folder as this yml
      - .:/app/data
    environment:
      - TZ=Asia/Shanghai
      - SECRET_KEY=change-this-to-random-string
      - PROXY_LISTEN=0.0.0.0

networks:
  default:
    driver: bridge
```

Open `http://localhost:5000` in your browser.
