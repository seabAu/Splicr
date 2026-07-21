#!/usr/bin/env bash

set -Eeuo pipefail

if (( $# != 9 )); then
  echo "Usage: remote-deploy.sh DEPLOY_ROOT RELEASE_ID IMAGE_REPOSITORY IMAGE_TAG HTTP_PORT PUBLIC_HOST PUBLIC_HTTPS_PORT NGINX_MODE HTTP_VHOST_MODE" >&2
  exit 64
fi

deploy_root=$1
release_id=$2
image_repository=$3
image_tag=$4
http_port=$5
public_host=$6
public_https_port=$7
nginx_mode=$8
http_vhost_mode=$9

if [[ "$deploy_root" != "/home/sites/splicr" ]]; then
  echo "The restricted deployment root must be /home/sites/splicr" >&2
  exit 64
fi
if [[ ! "$release_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$ ]]; then
  echo "Invalid release ID" >&2
  exit 64
fi
if [[ ! "$image_repository" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]]; then
  echo "Invalid image repository" >&2
  exit 64
fi
if [[ ! "$image_tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
  echo "Invalid image tag" >&2
  exit 64
fi
if [[ ! "$http_port" =~ ^[0-9]{1,5}$ ]] || (( http_port < 1 || http_port > 65535 )); then
  echo "Invalid private HTTP port" >&2
  exit 64
fi
if [[ ! "$public_host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$ ]]; then
  echo "Invalid public host" >&2
  exit 64
fi
if [[ ! "$public_https_port" =~ ^[0-9]{1,5}$ ]] || (( public_https_port < 1 || public_https_port > 65535 )); then
  echo "Invalid public HTTPS port" >&2
  exit 64
fi
if [[ "$public_https_port" == "80" ]]; then
  echo "The public HTTPS port cannot be the HTTP port" >&2
  exit 64
fi
if [[ "$http_port" == "80" || "$http_port" == "443" || "$public_https_port" == "$http_port" ]]; then
  echo "The private loopback port must be distinct from HTTP, HTTPS, and the public NGINX port" >&2
  exit 64
fi
if [[ "$nginx_mode" != "bootstrap" && "$nginx_mode" != "tls" ]]; then
  echo "NGINX mode must be bootstrap or tls" >&2
  exit 64
fi
if [[ "$http_vhost_mode" != "managed" && "$http_vhost_mode" != "external" ]]; then
  echo "HTTP vhost mode must be managed or external" >&2
  exit 64
fi

umask 077
shared_dir="$deploy_root/shared"
environment_file="$shared_dir/runtime.env"
vault_key_file="$shared_dir/secrets/vault.key"
data_dir="$shared_dir/data"
nginx_dir="$shared_dir/nginx"
acme_dir="$shared_dir/acme"
nginx_candidate="$nginx_dir/candidate.conf"
incoming_dir="$deploy_root/incoming/$release_id"
release_dir="$deploy_root/releases/$release_id"

require_private_file() {
  local path=$1
  local label=$2
  test -f "$path" || { echo "$label is missing: $path" >&2; exit 78; }
  local raw_mode
  raw_mode=$(stat -c '%a' "$path")
  local permissions=$((8#$raw_mode))
  if (( (permissions & 077) != 0 )); then
    echo "$label must not be accessible by group/other users (use mode 600 or 400)." >&2
    exit 78
  fi
}

require_private_file "$environment_file" "Runtime environment file"
require_private_file "$vault_key_file" "Vault key file"
test -d "$data_dir" || { echo "Persistent data directory is missing: $data_dir" >&2; exit 78; }
test -d "$nginx_dir" || { echo "Managed NGINX staging directory is missing: $nginx_dir" >&2; exit 78; }
test -d "$acme_dir" || { echo "ACME webroot is missing: $acme_dir" >&2; exit 78; }
test -f "$incoming_dir/compose.deploy.yaml" || { echo "The staged Compose file is missing." >&2; exit 78; }
test -f "$incoming_dir/remote-deploy.sh" || { echo "The staged deploy script is missing." >&2; exit 78; }
test -f "$incoming_dir/nginx-splicr.conf.template" || { echo "The staged TLS NGINX template is missing." >&2; exit 78; }
test -f "$incoming_dir/nginx-splicr-bootstrap.conf.template" || { echo "The staged bootstrap NGINX template is missing." >&2; exit 78; }
test -f "$incoming_dir/nginx-splicr-external-http.conf.template" || { echo "The staged external-HTTP TLS NGINX template is missing." >&2; exit 78; }
test -f "$incoming_dir/nginx-splicr-bootstrap-external-http.conf.template" || { echo "The staged external-HTTP bootstrap NGINX template is missing." >&2; exit 78; }

install -d -m 0750 "$deploy_root/releases"
if [[ -e "$release_dir" ]]; then
  echo "Release directory already exists: $release_dir" >&2
  exit 73
fi
mv "$incoming_dir" "$release_dir"
chmod 0700 "$release_dir/remote-deploy.sh"
chmod 0600 \
  "$release_dir/compose.deploy.yaml" \
  "$release_dir/nginx-splicr.conf.template" \
  "$release_dir/nginx-splicr-bootstrap.conf.template" \
  "$release_dir/nginx-splicr-external-http.conf.template" \
  "$release_dir/nginx-splicr-bootstrap-external-http.conf.template"

docker_config="$release_dir/.docker"
test -f "$docker_config/config.json" || {
  echo "The isolated GHCR credential is missing; the release cannot be pulled." >&2
  exit 78
}
export DOCKER_CONFIG="$docker_config"

cleanup_registry_auth() {
  rm -f "$docker_config/config.json"
  rmdir "$docker_config" >/dev/null 2>&1 || true
}
trap cleanup_registry_auth EXIT

release_environment="$release_dir/release.env"
printf '%s\n' \
  "SPLICR_IMAGE=ghcr.io/${image_repository}:${image_tag}" \
  "SPLICR_ENV_FILE=${environment_file}" \
  "SPLICR_DATA_ROOT=${data_dir}" \
  "SPLICR_VAULT_KEY_FILE=${vault_key_file}" \
  "SPLICR_HTTP_PORT=${http_port}" \
  > "$release_environment"
chmod 0600 "$release_environment"

https_authority=$public_host
if [[ "$public_https_port" != "443" ]]; then
  https_authority="${public_host}:${public_https_port}"
fi
if [[ "$nginx_mode" == "tls" && "$http_vhost_mode" == "managed" ]]; then
  nginx_template="$release_dir/nginx-splicr.conf.template"
elif [[ "$nginx_mode" == "tls" ]]; then
  nginx_template="$release_dir/nginx-splicr-external-http.conf.template"
elif [[ "$http_vhost_mode" == "managed" ]]; then
  nginx_template="$release_dir/nginx-splicr-bootstrap.conf.template"
else
  nginx_template="$release_dir/nginx-splicr-bootstrap-external-http.conf.template"
fi
rendered_nginx="$release_dir/nginx-splicr.conf"
sed \
  -e "s|__SPLICR_PUBLIC_HOST__|${public_host}|g" \
  -e "s|__SPLICR_PUBLIC_HTTPS_PORT__|${public_https_port}|g" \
  -e "s|__SPLICR_HTTPS_AUTHORITY__|${https_authority}|g" \
  -e "s|__SPLICR_HTTP_PORT__|${http_port}|g" \
  "$nginx_template" > "$rendered_nginx"
if grep -q '__SPLICR_' "$rendered_nginx"; then
  echo "The rendered NGINX site still contains an unresolved placeholder." >&2
  exit 65
fi
chmod 0600 "$rendered_nginx"

exec 9>"$deploy_root/.deploy.lock"
flock -w 900 9 || { echo "Another SPLICR deployment still holds the deployment lock." >&2; exit 75; }

compose() {
  local directory=$1
  shift
  docker compose \
    --project-name splicr \
    --project-directory "$directory" \
    --env-file "$environment_file" \
    --env-file "$directory/release.env" \
    --file "$directory/compose.deploy.yaml" \
    "$@"
}

previous_dir=""
if [[ -L "$deploy_root/current" ]]; then
  previous_dir=$(readlink -f "$deploy_root/current" || true)
  [[ "$previous_dir" == "$deploy_root/releases/"* ]] || previous_dir=""
fi
current_changed=false

restore_current_link() {
  [[ "$current_changed" == true ]] || return 0
  if [[ -n "$previous_dir" ]]; then
    local rollback_link="$deploy_root/.current-rollback-$release_id"
    rm -f "$rollback_link"
    ln -s "releases/$(basename "$previous_dir")" "$rollback_link"
    mv -Tf "$rollback_link" "$deploy_root/current"
  elif [[ -L "$deploy_root/current" ]]; then
    local current_target
    current_target=$(readlink -f "$deploy_root/current" || true)
    if [[ "$current_target" == "$release_dir" ]]; then
      rm -f "$deploy_root/current"
    fi
  fi
}

rollback() {
  local status=${1:-$?}
  trap - ERR HUP INT TERM
  echo "Deployment failed; attempting to restore the previous SPLICR release." >&2
  restore_current_link || echo "The current-release link could not be restored." >&2
  if [[ -n "$previous_dir" && -f "$previous_dir/compose.deploy.yaml" && -f "$previous_dir/release.env" ]]; then
    compose "$previous_dir" up -d --wait --wait-timeout 600 --no-build --remove-orphans || \
      echo "Automatic application rollback also failed; operator intervention is required." >&2
  else
    compose "$release_dir" down --remove-orphans >/dev/null 2>&1 || true
    echo "No previous release was available; the failed first release was stopped." >&2
  fi
  exit "$status"
}
trap 'rollback $?' ERR
trap 'rollback 129' HUP
trap 'rollback 130' INT
trap 'rollback 143' TERM

compose "$release_dir" config --quiet
compose "$release_dir" pull app
compose "$release_dir" up -d --wait --wait-timeout 600 --no-build --remove-orphans
curl --fail --show-error --silent --max-time 15 \
  "http://127.0.0.1:${http_port}/health" >/dev/null

printf '%s\n' \
  "release=$release_id" \
  "image_tag=$image_tag" \
  "nginx_mode=$nginx_mode" \
  "http_vhost_mode=$http_vhost_mode" \
  "public_url=https://${https_authority}/" \
  "deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$release_dir/deployment.txt"

next_link="$deploy_root/.current-$release_id"
ln -s "releases/$release_id" "$next_link"
current_changed=true
mv -Tf "$next_link" "$deploy_root/current"

candidate_tmp="$nginx_dir/.candidate-$release_id"
install -m 0644 "$rendered_nginx" "$candidate_tmp"
mv -Tf "$candidate_tmp" "$nginx_candidate"
sudo -n /usr/local/sbin/install-splicr-nginx-site apply "$deploy_root"

trap - ERR HUP INT TERM
current_changed=false
rm -f "$nginx_candidate"
compose "$release_dir" ps || true
if [[ "$nginx_mode" == "bootstrap" ]]; then
  echo "SPLICR release $release_id is healthy; NGINX is in ACME bootstrap mode."
else
  echo "SPLICR release $release_id is healthy at https://${https_authority}/."
fi
