# Hermes UI staging deployment

This directory contains examples only. Do not start the production port 8000
from these files. The existing live process and Open WebUI remain untouched.

## Credentials

Create a dedicated environment file at /etc/hermes/auth.env, owned by
root:root with mode 0600. It must contain HERMES_LOGIN_USERNAME,
HERMES_LOGIN_USER_ID, HERMES_LOGIN_PASSWORD_HASH, and
HERMES_SESSION_COOKIE_SECURE=true. It may set HERMES_SESSION_TTL_SECONDS.
Generate a salted hash interactively with:

    venv/bin/python -m api.auth

Do not put the password or hash in the repository .env. The current config
loader copies repository .env keys into the process environment, so auth keys
must not also appear there. The example systemd unit reads the protected file
as the system manager and runs one Uvicorn worker as arman. It is not installed.

## HTTPS staging

Caddy is not currently installed. The example Caddyfile listens only on
192.168.68.103:8443 and proxies to 127.0.0.1:8001. Install and validate
Caddy separately, then run it with:

    caddy validate --config deploy/Caddyfile.staging
    caddy run --config deploy/Caddyfile.staging

Caddy's internal CA root must be trusted on every browser used for testing.
The staging URL is https://192.168.68.103:8443/login. Restrict this staging
listener to the intended LAN in the host firewall. Verify that Uvicorn sees
the HTTPS scheme from the loopback proxy before testing browser login.

## Cutover guard

Keep the old 0.0.0.0:8000 process running throughout staging. Do not use
start.sh for staging: it calls pkill uvicorn. Once authentication, browser chat,
HTTPS, and network isolation pass, plan a separate production cutover.
