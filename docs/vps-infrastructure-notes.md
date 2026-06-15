# VPS Infrastructure Notes

Target host: `51.81.83.107`
Domain: `https://label.af5.org`

The VPS already uses Dokploy Traefik as the public edge:

- Traefik container: `dokploy-traefik`
- Traefik network: `dokploy-network`
- Docker Compose: `v5.1.4`
- Public ports: Traefik owns `80` and `443`
- Host Caddy is not installed and should not be installed for this app

Prepared label app state:

- App root: `/opt/label`
- Future source deployment directory: `/opt/label/app`
- Env file: `/opt/label/.env`, mode `600`, owned by `labeldeploy`
- Uploads: `/opt/label/shared/uploads`
- Postgres data: `/opt/label/shared/postgres`
- Backups: `/opt/label/backups`
- Deploy SSH user: `labeldeploy`
- Deploy user is in the `docker` group

Production routing convention:

- Attach the app `api` container to `dokploy-network`.
- Add Traefik labels to the `api` container for `label.af5.org`.
- Do not publish host ports from the app containers in production.
- Keep Postgres and worker off the public Traefik network.

Production env values already corrected on the VPS:

```text
TRAEFIK_NETWORK=dokploy-network
TRAEFIK_ENTRYPOINT=websecure
TRAEFIK_CERTRESOLVER=
```

Existing app convention confirmed from `shipshape-web`:

```text
traefik.docker.network=dokploy-network
entrypoints=web / websecure
tls.certresolver=letsencrypt
```

GitHub Actions variables and secrets to configure:

```text
Variables:
  VPS_HOST=51.81.83.107
  VPS_USER=labeldeploy
  BASE_URL=https://label.af5.org

Secrets:
  VPS_SSH_PRIVATE_KEY=<private key for the labeldeploy deploy user>
```

After `VPS_SSH_PRIVATE_KEY` is copied into GitHub Actions, keep the VPS-side copy protected and readable only by trusted operators.

Firewall status:

```text
22/tcp allowed
80/tcp allowed
443/tcp allowed
IPv6 equivalents allowed
UFW active
```

Temporary bootstrapping containers are not part of the production compose stack, so they do not
conflict with the deployed app.
