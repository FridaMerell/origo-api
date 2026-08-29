#!/usr/bin/env bash
set -Eeuo pipefail

# DigitalOcean startup script for db.origo.fåvitsko.se
# Target image: Ubuntu 24.04 LTS
#
# This provisions the host only. It intentionally does not fetch application
# code or run Django migrations. Upload the application to /srv/origo/app and
# install its Python requirements into /srv/origo/venv after first boot.

APP_USER="origo"
APP_GROUP="origo"
APP_ROOT="/srv/origo"
APP_DIR="${APP_ROOT}/app"
VENV_DIR="${APP_ROOT}/venv"
ENV_DIR="/etc/origo"
ENV_FILE="${ENV_DIR}/origo.env"
DOMAIN_ASCII="db.origo.xn--fvitsko-5wa.se"
DB_NAME="origo"
DB_USER="origo"

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get upgrade --yes
apt-get install --yes \
  build-essential \
  ca-certificates \
  caddy \
  curl \
  libpq-dev \
  openssl \
  postgresql \
  postgresql-contrib \
  python3 \
  python3-dev \
  python3-pip \
  python3-venv \
  ufw

if ! id "${APP_USER}" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "${APP_ROOT}" --shell /usr/sbin/nologin "${APP_USER}"
fi

install -d -m 0750 -o "${APP_USER}" -g "${APP_GROUP}" "${APP_ROOT}" "${APP_DIR}"
install -d -m 0750 -o root -g "${APP_GROUP}" "${ENV_DIR}"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
  "${VENV_DIR}/bin/pip" install gunicorn psycopg[binary]
fi
chown -R "${APP_USER}:${APP_GROUP}" "${VENV_DIR}"

systemctl enable --now postgresql

if [[ ! -f "${ENV_FILE}" ]]; then
  DB_PASSWORD="$(openssl rand -base64 36 | tr -d '\n' | tr '/+' '_-')"

  runuser -u postgres -- psql --set=ON_ERROR_STOP=1 \
    --set=db_user="${DB_USER}" \
    --set=db_password="${DB_PASSWORD}" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'db_user', :'db_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'db_user')\gexec
SQL

  runuser -u postgres -- psql --set=ON_ERROR_STOP=1 \
    --set=db_name="${DB_NAME}" \
    --set=db_user="${DB_USER}" <<'SQL'
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'db_user')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')\gexec
SQL

  SECRET_KEY="$(openssl rand -base64 64 | tr -d '\n')"
  install -m 0640 -o root -g "${APP_GROUP}" /dev/null "${ENV_FILE}"
  {
    printf 'DJANGO_SECRET_KEY=%s\n' "${SECRET_KEY}"
    printf 'DJANGO_DEBUG=False\n'
    printf 'DJANGO_ALLOWED_HOSTS=%s\n' "${DOMAIN_ASCII}"
    printf 'DATABASE_URL=postgresql://%s:%s@127.0.0.1:5432/%s\n' "${DB_USER}" "${DB_PASSWORD}" "${DB_NAME}"
  } >"${ENV_FILE}"
fi

# PostgreSQL remains private and accepts connections only from this Droplet.
PG_CONF="$(find /etc/postgresql -path '*/main/postgresql.conf' -print -quit)"
PG_HBA="$(find /etc/postgresql -path '*/main/pg_hba.conf' -print -quit)"
if [[ -n "${PG_CONF}" ]]; then
  sed -i "s/^[#[:space:]]*listen_addresses[[:space:]]*=.*/listen_addresses = '127.0.0.1'/" "${PG_CONF}"
fi
if [[ -n "${PG_HBA}" ]] && ! grep -q '^host[[:space:]]\+origo[[:space:]]\+origo[[:space:]]\+127\.0\.0\.1/32' "${PG_HBA}"; then
  printf 'host origo origo 127.0.0.1/32 scram-sha-256\n' >>"${PG_HBA}"
fi
systemctl restart postgresql

cat >/usr/local/sbin/start-origo <<'START_SCRIPT'
#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="/srv/origo/app"
WSGI_FILE="$(find "${APP_DIR}" -type f -name wsgi.py -not -path '*/site-packages/*' -print -quit)"

if [[ -z "${WSGI_FILE}" ]]; then
  echo "No Django wsgi.py found below ${APP_DIR}" >&2
  exit 1
fi

WSGI_PACKAGE="$(basename "$(dirname "${WSGI_FILE}")")"
exec /srv/origo/venv/bin/gunicorn \
  --chdir "${APP_DIR}" \
  --workers 2 \
  --threads 2 \
  --timeout 60 \
  --access-logfile - \
  --error-logfile - \
  --bind 127.0.0.1:8000 \
  "${WSGI_PACKAGE}.wsgi:application"
START_SCRIPT
chmod 0755 /usr/local/sbin/start-origo

cat >/etc/systemd/system/origo.service <<'SYSTEMD_UNIT'
[Unit]
Description=Origo Django API
After=network-online.target postgresql.service
Wants=network-online.target
Requires=postgresql.service
ConditionPathExists=/srv/origo/app/manage.py

[Service]
Type=simple
User=origo
Group=origo
WorkingDirectory=/srv/origo/app
EnvironmentFile=/etc/origo/origo.env
ExecStart=/usr/local/sbin/start-origo
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/srv/origo

[Install]
WantedBy=multi-user.target
SYSTEMD_UNIT

cat >/etc/caddy/Caddyfile <<CADDYFILE
${DOMAIN_ASCII} {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }
}
CADDYFILE

caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable origo.service
systemctl enable --now caddy

ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

cat >/root/ORIGO-NEXT-STEPS.txt <<'NEXT_STEPS'
Origo host provisioning is complete.

1. Point the DNS A record for db.origo.fåvitsko.se to this Droplet's public IPv4 address.
2. Upload the Django project contents to /srv/origo/app.
3. Ensure the uploaded files are owned by user/group origo.
4. Install the project's Python requirements into /srv/origo/venv.
5. Verify that Django settings read DATABASE_URL, DJANGO_SECRET_KEY,
   DJANGO_DEBUG, and DJANGO_ALLOWED_HOSTS from /etc/origo/origo.env.
6. Run your Django migration and static-file workflow yourself.
7. Start or restart the origo systemd service.

Database credentials and Django secrets are stored in:
  /etc/origo/origo.env

PostgreSQL listens on localhost only and is not exposed by the firewall.
The public Unicode hostname is represented in Caddy as:
  db.origo.xn--fvitsko-5wa.se
NEXT_STEPS

echo "Origo provisioning completed. See /root/ORIGO-NEXT-STEPS.txt."
