# SPLICR production deployment

This runbook deploys SPLICR to `/home/sites/splicr` on the Ubuntu host reached over SSH at
`147.182.184.250`. FastAPI serves both the browser studio and `/v1`; there is no separate client
process. Docker publishes the application only on a private loopback port, and the server's existing
NGINX installation exposes it as `https://splicr.seangb.com/` on the shared HTTPS listener.

SPLICR writes its NGINX request and proxy errors to
`/home/logs/nginx/splicr.access.log` and `/home/logs/nginx/splicr.error.log`. The restricted helper
creates these paths without allowing deployment-user-controlled symlinks, and a dedicated
logrotate policy keeps 14 daily compressed rotations.

The hostname resolves to the server's DigitalOcean reserved address `138.197.229.133`, which forwards
to this droplet. NGINX uses SNI to select SPLICR on port `443`; its site is deliberately not a
`default_server`, so unrelated portfolio projects retain their existing fallback behavior. The
installer owns only `sites-available/splicr.conf` and its matching `sites-enabled` symlink.

Each push to `main` builds and tests an immutable image, publishes it to GHCR, uploads Compose plus
the versioned NGINX templates, starts the new container, checks `/health`, atomically installs and
reloads the SPLICR NGINX site, and rolls back on failure. Persistent jobs and credentials remain
under `/home/sites/splicr/shared`.

## Deployment checklist

- [ ] Confirm that private port `8000` is available and `splicr.seangb.com` resolves to this host.
- [ ] Create the dedicated `splicr-deploy` account and Actions SSH key.
- [ ] Install Docker, Compose, NGINX, `curl`, `flock`, `logrotate`, and a supported Certbot release.
- [ ] Create `/home/sites/splicr`, its persistent state, runtime environment, and vault key.
- [ ] Install the restricted NGINX helper and its two-command sudo rule.
- [ ] Create the root-owned Basic Auth file.
- [ ] Add the two GitHub secrets and nine variables below.
- [ ] Deploy once with `SPLICR_NGINX_MODE=bootstrap`.
- [ ] Issue the `splicr.seangb.com` certificate and verify automatic renewal.
- [ ] Change `SPLICR_NGINX_MODE=tls`, redeploy, and test the authenticated studio.

## 1. Inspect the shared host and choose ports

Run these on the server before changing anything:

```bash
sudo ss -ltnp
sudo nginx -T | grep -nE 'listen|server_name'
```

The defaults use:

- `8000` for Docker's loopback-only upstream (`127.0.0.1:8000`);
- shared port `80` for SPLICR's hostname-specific ACME challenge vhost;
- shared port `443` for SPLICR's hostname-specific TLS vhost.

The July 21, 2026 host inspection confirms that `8000` is unused. Ports `80` and `443` are already
used by NGINX, as expected; hostname-based virtual servers safely share them. Confirm DNS and ensure
there is no pre-existing SPLICR vhost before deployment:

```bash
getent ahostsv4 splicr.seangb.com
sudo grep -RsnE 'server_name[[:space:]].*splicr\.seangb\.com' /etc/nginx/sites-enabled /etc/nginx/conf.d || true
```

DNS currently returns `138.197.229.133`, and public ACME probes confirm that address forwards to this
droplet. Use `SPLICR_HTTP_VHOST_MODE=managed`; the deployment creates the hostname-specific port-80
challenge server without editing an unrelated portfolio vhost. The root helper rejects duplicate
SPLICR server names. SPLICR proxies at `/`, rather than `/splicr/`, because its assets and API use
absolute `/assets` and `/v1` paths.

## 2. Create the deployment account and SSH identity

The deployment-specific account is `splicr-deploy`. It does not use the previously disclosed shared
account or password. On the server:

```bash
id splicr-deploy || sudo adduser --disabled-password --gecos "" splicr-deploy
```

On a trusted workstation—not inside the server's root shell—create a dedicated key with an empty
passphrase so a non-interactive Actions runner can use it. Protect the private key with the GitHub
`production` environment. In Windows PowerShell:

```powershell
ssh-keygen -t ed25519 -a 100 -C "splicr-github-actions" -f "$HOME\.ssh\splicr-actions"
scp -P 22 "$HOME\.ssh\splicr-actions.pub" YOUR_ADMIN_USER@147.182.184.250:/tmp/splicr-actions.pub
```

`YOUR_ADMIN_USER` must be an existing account that can already authenticate over SSH. Do not use
`root` when root SSH login is disabled. From that administrator session on the server, install the
key with the OpenSSH `restrict` option:

```bash
sudo install -d -m 0700 -o splicr-deploy -g splicr-deploy ~splicr-deploy/.ssh
sudo install -m 0600 -o splicr-deploy -g splicr-deploy /tmp/splicr-actions.pub ~splicr-deploy/.ssh/authorized_keys
sudo sed -i '1s/^/restrict /' ~splicr-deploy/.ssh/authorized_keys
rm /tmp/splicr-actions.pub
```

If the server is currently reachable only through its provider console, skip `scp`. On the Windows
workstation, display and copy the single public-key line:

```powershell
Get-Content "$HOME\.ssh\splicr-actions.pub"
```

Then, from the server's root console, create the file with `nano`, paste `restrict ` followed by that
public-key line, save, and set ownership:

```bash
install -d -m 0700 -o splicr-deploy -g splicr-deploy /home/splicr-deploy/.ssh
nano /home/splicr-deploy/.ssh/authorized_keys
chown splicr-deploy:splicr-deploy /home/splicr-deploy/.ssh/authorized_keys
chmod 0600 /home/splicr-deploy/.ssh/authorized_keys
```

Finally, test the exact identity from Windows before adding it to GitHub:

```powershell
ssh -i "$HOME\.ssh\splicr-actions" -p 22 splicr-deploy@147.182.184.250
```

GitHub Actions never needs an SSH password.

## 3. Install server prerequisites

These commands target supported Ubuntu releases. For another distribution, follow Docker's matching
official installation guide rather than changing repository names by guesswork.

```bash
cat /etc/os-release
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg openssl nginx apache2-utils util-linux logrotate snapd ufw
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker nginx
sudo usermod -aG docker splicr-deploy
```

Log out and back in after changing group membership, then verify:

```bash
docker version
docker compose version
curl --version
flock --version
logrotate --version
```

Membership in the `docker` group is effectively root-equivalent. Keep this account deployment-only,
protect `main` and the GitHub `production` environment, and never reuse its private key.

## 4. Create persistent state under `/home/sites`

UID/GID `10001` matches the non-root user inside the image. Modes `0751` on the deployment root and
`shared` let the NGINX worker traverse to the ACME webroot without listing either directory; the
data, secrets, and NGINX staging directories remain separately locked down.

```bash
sudo install -d -m 0751 -o splicr-deploy -g splicr-deploy /home/sites/splicr
sudo install -d -m 0750 -o splicr-deploy -g splicr-deploy /home/sites/splicr/incoming /home/sites/splicr/releases
sudo install -d -m 0751 -o splicr-deploy -g splicr-deploy /home/sites/splicr/shared
sudo install -d -m 0750 -o splicr-deploy -g splicr-deploy /home/sites/splicr/shared/nginx /home/sites/splicr/shared/secrets
sudo install -d -m 0755 -o splicr-deploy -g splicr-deploy /home/sites/splicr/shared/acme
sudo install -d -m 0700 -o 10001 -g 10001 /home/sites/splicr/shared/data
sudo install -m 0600 -o splicr-deploy -g splicr-deploy /dev/null /home/sites/splicr/shared/runtime.env
sudo -u splicr-deploy sh -c "umask 077; openssl rand -base64 32 | tr '+/' '-_' > /home/sites/splicr/shared/secrets/vault.key"
sudo chown 10001:10001 /home/sites/splicr/shared/secrets/vault.key
sudo chmod 400 /home/sites/splicr/shared/secrets/vault.key
```

Host-side tools may display owner `10001:10001` as `UNKNOWN:UNKNOWN`; that is expected because the
identity is named only inside the container. Do not create a matching host account or replace that
ownership with `splicr-deploy`.

Transfer the safe runtime template from the repository:

```bash
scp -P 22 deploy/runtime.env.example splicr-deploy@147.182.184.250:/tmp/splicr-runtime.env
```

On the server, install and edit it. Rotate any provider key previously pasted into chat before
putting the replacement here. Provider keys and the vault key never belong in GitHub.

```bash
sudo install -m 0600 -o splicr-deploy -g splicr-deploy /tmp/splicr-runtime.env /home/sites/splicr/shared/runtime.env
sudo -u splicr-deploy nano /home/sites/splicr/shared/runtime.env
rm /tmp/splicr-runtime.env
```

Keep `SPLICR_CORS_ORIGINS=https://splicr.seangb.com` aligned with the public origin. The
vault key encrypts API-resource keys saved through the UI. Losing it makes that vault unrecoverable;
storing it beside a copied data backup defeats the encryption.

## 5. Install the restricted NGINX integration

The workflow uploads and renders the NGINX configuration on every release. A small root-owned helper
is installed once so Actions can atomically replace only SPLICR's site, run `nginx -t`, reload, and
restore the previous site if either step fails.

From the repository:

```bash
scp -P 22 deploy/install-nginx-site.sh deploy/reload-nginx-after-renewal.sh deploy/splicr-nginx.logrotate splicr-deploy@147.182.184.250:/tmp/
```

On the server:

```bash
sudo install -m 0755 -o root -g root /tmp/install-nginx-site.sh /usr/local/sbin/install-splicr-nginx-site
sudo install -m 0644 -o root -g root /tmp/splicr-nginx.logrotate /etc/logrotate.d/splicr-nginx
printf '%s\n' 'splicr-deploy ALL=(root) NOPASSWD: /usr/local/sbin/install-splicr-nginx-site check /home/sites/splicr, /usr/local/sbin/install-splicr-nginx-site apply /home/sites/splicr' | sudo tee /etc/sudoers.d/splicr-nginx >/dev/null
sudo chmod 0440 /etc/sudoers.d/splicr-nginx
sudo visudo -cf /etc/sudoers.d/splicr-nginx
sudo -u splicr-deploy sudo -n /usr/local/sbin/install-splicr-nginx-site check /home/sites/splicr
sudo htpasswd -c /etc/nginx/.htpasswd-splicr ember
sudo chown root:www-data /etc/nginx/.htpasswd-splicr
sudo chmod 0640 /etc/nginx/.htpasswd-splicr
sudo install -d -m 0755 /etc/letsencrypt/renewal-hooks/deploy
# Inspect existing executable hooks first. Install this only when no existing
# host-global hook already validates and reloads NGINX.
sudo find /etc/letsencrypt/renewal-hooks -maxdepth 3 -type f -executable -ls
sudo install -m 0755 -o root -g root /tmp/reload-nginx-after-renewal.sh /etc/letsencrypt/renewal-hooks/deploy/splicr-reload-nginx
sudo logrotate --debug /etc/logrotate.d/splicr-nginx
rm /tmp/install-nginx-site.sh /tmp/reload-nginx-after-renewal.sh /tmp/splicr-nginx.logrotate
```

Inspect any existing executable hook before installing the SPLICR hook. If a host-global hook
already runs `nginx -t` and reloads NGINX after successful renewal, reuse it and skip SPLICR's hook
to avoid duplicate reloads. The reload hook is host integration, not an application secret.

The helper refuses unexpected roots, unmanaged SPLICR site files, unexpected symlink targets,
duplicate SPLICR vhosts, default-server takeover, and candidates without the managed marker. It takes a
root-owned snapshot before validation and installation. The helper narrows filesystem targets and
provides atomic rollback; reviewed/protected `main` remains the configuration trust boundary, and
Docker-group membership is already root-equivalent. Do not grant `splicr-deploy` additional general
passwordless sudo for NGINX or `systemctl`.

## 6. Configure GitHub Actions

In **Settings -> Secrets and variables -> Actions**, create a `production` environment restricted to
`main`. Add these secrets at repository or environment scope:

| Secret | Value |
| --- | --- |
| `DEPLOY_SSH_PRIVATE_KEY` | Entire contents of the dedicated `splicr-actions` private key |
| `DEPLOY_SSH_KNOWN_HOSTS` | Verified SSH host-key line for `147.182.184.250` |

Obtain the host key from a trusted workstation and compare its fingerprint with the server's local
host public key before saving it:

```bash
ssh-keyscan -p 22 -t ed25519 147.182.184.250 > splicr-known-hosts
ssh-keygen -lf splicr-known-hosts
# Run this second command in an administrator shell on the server:
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Add these Actions variables:

| Variable | Initial value | Purpose |
| --- | --- | --- |
| `DEPLOY_HOST` | `147.182.184.250` | SSH destination |
| `DEPLOY_PORT` | `22` | SSH port |
| `DEPLOY_USER` | `splicr-deploy` | Dedicated deployment account |
| `DEPLOY_PATH` | `/home/sites/splicr` | Fixed release and shared-state root |
| `SPLICR_HTTP_PORT` | `8000` | Private loopback Docker upstream |
| `SPLICR_PUBLIC_HOST` | `splicr.seangb.com` | NGINX server name and certificate identifier |
| `SPLICR_PUBLIC_HTTPS_PORT` | `443` | Shared HTTPS port selected through SNI |
| `SPLICR_NGINX_MODE` | `bootstrap` | ACME-only first deployment; later change to `tls` |
| `SPLICR_HTTP_VHOST_MODE` | `managed` | SPLICR owns its hostname-specific port-80 challenge vhost |

The built-in short-lived `GITHUB_TOKEN` publishes and pulls the matching GHCR image through an
isolated per-release Docker configuration, which the workflow deletes after rollout. No GHCR token
or provider key needs to be added to Actions.

## 7. Make the first ACME-bootstrap release

Ports 80 and 443 are already open for the other NGINX sites. Confirm the host and provider firewalls
still allow them before the bootstrap release:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

Commit the intended application and deployment files, then push `main`:

```bash
git add .dockerignore .env.example .gitattributes .gitignore .github AGENTS.md Dockerfile README.md compose.deploy.yaml compose.yaml deploy docs pyproject.toml src tests uv.lock
git status --short
git commit -m "Prepare SPLICR production deployment"
git push --set-upstream origin main
```

This deliberate add list excludes the unrelated `LICENSE.txt`; add it separately only if intended.

With `SPLICR_HTTP_VHOST_MODE=managed`, the first workflow finishes with an ACME-only port-80 vhost:
it serves `/.well-known/acme-challenge/` and returns `503` everywhere else. It does not yet install a
TLS vhost, expose Basic Auth, or serve the studio/API over plaintext HTTP.

```bash
curl -i http://splicr.seangb.com/
sudo nginx -T | grep -n 'SPLICR-MANAGED-SITE'
```

## 8. Issue and automatically renew the hostname certificate

Issue a separate certificate for `splicr.seangb.com` through the bootstrap vhost's webroot. Keeping
the lineage separate avoids changing the identifiers or renewal behavior of portfolio certificates.

Use a current supported Certbot release. These commands install the official Snap distribution when
the host does not already have it:

```bash
certbot --version || true
sudo snap install core
sudo snap refresh core
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/local/bin/certbot
certbot --version
```

On a shared host that already renews certificates through Ubuntu's APT package, do not remove that
package or disable its timer until the Snap client has read the existing lineages and successfully
simulated every renewal. The Snap and APT clients share `/etc/letsencrypt`, so first run the Snap
binary explicitly:

```bash
sudo /snap/bin/certbot certificates
sudo /snap/bin/certbot renew --dry-run
```

Fix any individual challenge-routing failure before switching timers. A webroot certificate must
have a matching `/.well-known/acme-challenge/` NGINX location that serves the lineage's recorded
`webroot_path` directly instead of redirecting it into an application. Once every simulated renewal
succeeds, make the Snap command the default and disable only the older APT timer:

```bash
sudo ln -sf /snap/bin/certbot /usr/local/bin/certbot
sudo systemctl disable --now certbot.timer
hash -r
command -v certbot
readlink -f "$(command -v certbot)"
certbot --version
systemctl status snap.certbot.renew.timer --no-pager
```

`command -v certbot` should report `/usr/local/bin/certbot`. On Snap installations,
`readlink -f` may report `/usr/bin/snap` rather than `/snap/bin/certbot` because the latter is a
launcher symlink; the authoritative checks are the reported Certbot version and the active
`snap.certbot.renew.timer`.

Keep the APT packages installed until the existing sites and SPLICR have completed a successful
renewal cycle under Snap. Package removal is optional cleanup after that observation period; never
purge `/etc/letsencrypt`.

Issue the trusted hostname certificate and confirm its files:

```bash
sudo certbot certonly --webroot --webroot-path /home/sites/splicr/shared/acme -d splicr.seangb.com
sudo ls -l /etc/letsencrypt/live/splicr.seangb.com/fullchain.pem /etc/letsencrypt/live/splicr.seangb.com/privkey.pem
```

Test the reload hook installed in step 5 and confirm the renewal timer is active:

```bash
sudo certbot renew --dry-run --run-deploy-hooks
sudo systemctl list-timers --all | grep -E 'certbot|snap.certbot'
```

Certificate issuance is deliberately a one-time host operation rather than an Actions step: it
requires accepting CA terms and verifying host-global port 80 and certificate state. Renewal is
fully automatic afterward.

## 9. Enable production HTTPS

Change the GitHub variable `SPLICR_NGINX_MODE` from `bootstrap` to `tls`, then run the workflow from
the Actions tab (or push the next commit). The deploy script renders the configured host and both
ports, health-checks the new container, and asks the restricted helper to install the TLS site.

Confirm the firewall changes from step 7 while leaving the private upstream closed:

```bash
sudo ufw status
```

Verify both layers:

```bash
curl --fail http://127.0.0.1:8000/health
curl -I http://splicr.seangb.com/
curl -I https://splicr.seangb.com/
readlink -f /home/sites/splicr/current
docker compose --project-name splicr --project-directory /home/sites/splicr/current --env-file /home/sites/splicr/shared/runtime.env --env-file /home/sites/splicr/current/release.env --file /home/sites/splicr/current/compose.deploy.yaml ps
```

The unauthenticated HTTPS request should return `401`; the browser should show a trusted certificate
and Basic Auth prompt. Then import a short document, save a temporary API resource, restart the
container, and confirm the job and encrypted resource persist.

## Operations

- Keep one app container and one Uvicorn worker. The SQLite-backed queue is not designed for
  horizontal replicas.
- NGINX accepts up to 30 MiB per request, leaves request buffering enabled to protect Uvicorn from
  slow clients, disables response buffering for large audio playback, and preserves SPLICR's detailed
  provider error responses.
- The image includes LibreOffice Writer so legacy `.doc` import works; this intentionally makes the
  image larger. DOCX, ODT, Markdown, JSON, and text import do not depend on LibreOffice.
- A job can use several gigabytes of PCM plus its final WAV. Monitor free space under
  `/home/sites/splicr/shared/data`.
- Back up `shared/data`, `shared/secrets/vault.key`, and `shared/runtime.env`; store the vault key and
  runtime environment separately from ordinary data backups. Stop the app for a filesystem-level
  SQLite-consistent backup.
- Keep useful `/home/sites/splicr/releases/*` directories for rollback, and periodically prune old
  releases and GHCR images after a verified backup.
- Monitor `https://splicr.seangb.com/` and alert on certificate expiry or renewal failure.
- SPLICR's NGINX access and error logs are `/home/logs/nginx/splicr.access.log` and
  `/home/logs/nginx/splicr.error.log`; its dedicated logrotate policy retains 14 daily rotations.
  Application logs are available with the same Compose arguments shown above plus
  `logs --tail 200 app`.
- If NGINX validation or reload fails, the root helper restores the previous SPLICR site and the
  deployment script restores the previous container and `current` link. Other NGINX site files are
  never modified.

Official references: [Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[Compose services](https://docs.docker.com/reference/compose-file/services/),
[GitHub deployment environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments),
[Certbot webroot authentication](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot),
and [NGINX HTTPS/SNI behavior](https://nginx.org/en/docs/http/configuring_https_servers.html).
