#!/bin/bash

set -Eeuo pipefail

PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

readonly EXPECTED_ROOT="/home/sites/splicr"
readonly CANDIDATE="$EXPECTED_ROOT/shared/nginx/candidate.conf"
readonly AVAILABLE="/etc/nginx/sites-available/splicr.conf"
readonly ENABLED="/etc/nginx/sites-enabled/splicr.conf"
readonly MARKER="# SPLICR-MANAGED-SITE v1"
readonly LOG_DIRECTORY="/home/logs/nginx"
readonly ACCESS_LOG="$LOG_DIRECTORY/splicr.access.log"
readonly ERROR_LOG="$LOG_DIRECTORY/splicr.error.log"

usage() {
  echo "Usage: install-splicr-nginx-site {check|apply} /home/sites/splicr" >&2
  exit 64
}

(( EUID == 0 )) || { echo "This helper must run as root." >&2; exit 77; }
(( $# == 2 )) || usage
action=$1
deploy_root=$2
[[ "$action" == "check" || "$action" == "apply" ]] || usage
[[ "$deploy_root" == "$EXPECTED_ROOT" ]] || {
  echo "Refusing unexpected deployment root: $deploy_root" >&2
  exit 64
}

for command_path in /usr/sbin/nginx /usr/bin/systemctl /usr/bin/install /usr/bin/getent; do
  [[ -x "$command_path" ]] || { echo "Required command is missing: $command_path" >&2; exit 69; }
done
/usr/bin/getent group adm >/dev/null || { echo "Required log-reader group is missing: adm" >&2; exit 69; }
/usr/bin/getent passwd www-data >/dev/null || { echo "Required NGINX account is missing: www-data" >&2; exit 69; }
[[ -d /etc/nginx/sites-available && -d /etc/nginx/sites-enabled ]] || {
  echo "The Debian/Ubuntu NGINX sites-available layout is required." >&2
  exit 69
}

validate_managed_file() {
  local path=$1
  [[ -f "$path" && ! -L "$path" ]] || {
    echo "Refusing non-regular NGINX site file: $path" >&2
    return 1
  }
  [[ $(head -n 1 "$path") == "$MARKER" ]] || {
    echo "Refusing NGINX site file without the SPLICR managed marker: $path" >&2
    return 1
  }
}

validate_enabled_path() {
  if [[ -e "$ENABLED" || -L "$ENABLED" ]]; then
    [[ -L "$ENABLED" ]] || {
      echo "Refusing to replace unmanaged path: $ENABLED" >&2
      return 1
    }
    local resolved
    resolved=$(readlink -f "$ENABLED" || true)
    [[ "$resolved" == "$AVAILABLE" ]] || {
      echo "Refusing unexpected SPLICR site symlink target: $resolved" >&2
      return 1
    }
  fi
}

ensure_log_directory() {
  if [[ ! -e "$LOG_DIRECTORY" && ! -L "$LOG_DIRECTORY" ]]; then
    /usr/bin/install -d -m 0750 -o root -g adm "$LOG_DIRECTORY"
  fi
  [[ -d "$LOG_DIRECTORY" && ! -L "$LOG_DIRECTORY" ]] || {
    echo "Refusing unsafe SPLICR NGINX log directory: $LOG_DIRECTORY" >&2
    return 1
  }
  [[ $(readlink -f "$LOG_DIRECTORY") == "$LOG_DIRECTORY" ]] || {
    echo "Refusing redirected SPLICR NGINX log directory: $LOG_DIRECTORY" >&2
    return 1
  }
  [[ $(stat -c '%U' "$LOG_DIRECTORY") == "root" ]] || {
    echo "The SPLICR NGINX log directory must be owned by root." >&2
    return 1
  }
  local raw_mode
  raw_mode=$(stat -c '%a' "$LOG_DIRECTORY")
  local permissions=$((8#$raw_mode))
  (( (permissions & 022) == 0 )) || {
    echo "The SPLICR NGINX log directory must not be group/other writable." >&2
    return 1
  }
}

ensure_log_file() {
  local path=$1
  if [[ -e "$path" || -L "$path" ]]; then
    [[ -f "$path" && ! -L "$path" ]] || {
      echo "Refusing unsafe SPLICR NGINX log file: $path" >&2
      return 1
    }
    [[ $(stat -c '%U' "$path") == "root" || $(stat -c '%U' "$path") == "www-data" ]] || {
      echo "Unexpected owner for SPLICR NGINX log file: $path" >&2
      return 1
    }
    local raw_mode
    raw_mode=$(stat -c '%a' "$path")
    local permissions=$((8#$raw_mode))
    (( (permissions & 022) == 0 )) || {
      echo "The SPLICR NGINX log file must not be group/other writable: $path" >&2
      return 1
    }
  else
    /usr/bin/install -m 0640 -o root -g adm /dev/null "$path"
  fi
}

if [[ -e "$AVAILABLE" || -L "$AVAILABLE" ]]; then
  validate_managed_file "$AVAILABLE"
fi
validate_enabled_path
/usr/sbin/nginx -t

if [[ "$action" == "check" ]]; then
  echo "The SPLICR NGINX installer is ready."
  exit 0
fi

[[ -f "$CANDIDATE" && ! -L "$CANDIDATE" ]] || {
  echo "Refusing non-regular candidate NGINX site: $CANDIDATE" >&2
  exit 65
}

candidate_snapshot=$(mktemp /etc/nginx/sites-available/.splicr.snapshot.XXXXXX)
backup=$(mktemp /etc/nginx/sites-available/.splicr.backup.XXXXXX)
candidate_tmp=$(mktemp /etc/nginx/sites-available/.splicr.candidate.XXXXXX)
had_available=false
had_enabled=false
committed=false

cleanup() {
  rm -f "$candidate_snapshot" "$backup" "$candidate_tmp"
}
trap cleanup EXIT

# Snapshot the user-writable candidate once, then validate and install only the
# root-owned snapshot so a concurrent replacement cannot change validated data.
/usr/bin/install -m 0600 -o root -g root "$CANDIDATE" "$candidate_snapshot"
validate_managed_file "$candidate_snapshot"
candidate_size=$(stat -c '%s' "$candidate_snapshot")
(( candidate_size > 0 && candidate_size <= 65536 )) || {
  echo "The candidate NGINX site has an unexpected size." >&2
  exit 65
}

candidate_tls_port=$(awk '
  $1 == "listen" && $0 ~ /ssl/ {
    endpoint = $2
    sub(/^.*:/, "", endpoint)
    sub(/;$/, "", endpoint)
    print endpoint
    exit
  }
' "$candidate_snapshot")
candidate_tls_is_default=false
if grep -Eq '^[[:space:]]*listen[[:space:]]+[^;]*ssl[^;]*default_server;' "$candidate_snapshot"; then
  candidate_tls_is_default=true
fi
if [[ -n "$candidate_tls_port" && "$candidate_tls_is_default" == true ]]; then
  current_owns_port=false
  if [[ -f "$AVAILABLE" ]] && grep -Eq \
    "^[[:space:]]*listen[[:space:]]+${candidate_tls_port}[[:space:]]+ssl[[:space:]]+default_server;" \
    "$AVAILABLE"; then
    current_owns_port=true
  fi
  if [[ "$current_owns_port" == false ]] && /usr/sbin/nginx -T 2>&1 | awk -v port="$candidate_tls_port" '
    $1 == "listen" {
      endpoint = $2
      sub(/;$/, "", endpoint)
      if (endpoint == port || endpoint ~ (":" port "$") ) {
        found = 1
      }
    }
    END { exit(found ? 0 : 1) }
  '; then
    echo "Refusing to become the default NGINX server on occupied port $candidate_tls_port." >&2
    exit 73
  fi
fi

manages_http=false
if grep -Fxq '# SPLICR-MANAGES-HTTP-VHOST' "$candidate_snapshot"; then
  manages_http=true
fi
candidate_public_host=$(awk '
  $1 == "server_name" {
    host = $2
    sub(/;$/, "", host)
    print host
    exit
  }
' "$candidate_snapshot")
if [[ "$manages_http" == true || -n "$candidate_tls_port" ]]; then
  [[ -n "$candidate_public_host" ]] || {
    echo "The NGINX candidate does not declare a server name." >&2
    exit 65
  }
fi

restore_previous() {
  local status=$?
  trap - ERR HUP INT TERM
  if [[ "$committed" == true ]]; then
    echo "NGINX activation failed; restoring the previous SPLICR site." >&2
    if [[ "$had_available" == true ]]; then
      /usr/bin/install -m 0644 -o root -g root "$backup" "$candidate_tmp"
      mv -Tf "$candidate_tmp" "$AVAILABLE"
    else
      rm -f "$AVAILABLE"
    fi
    if [[ "$had_enabled" == true ]]; then
      ln -sfn ../sites-available/splicr.conf "$ENABLED"
    else
      rm -f "$ENABLED"
    fi
    /usr/sbin/nginx -t && /usr/bin/systemctl reload nginx || \
      echo "The prior NGINX configuration also failed to reload; operator intervention is required." >&2
  fi
  cleanup
  exit "$status"
}
trap restore_previous ERR HUP INT TERM

if [[ -f "$AVAILABLE" ]]; then
  cp -p "$AVAILABLE" "$backup"
  had_available=true
fi
if [[ -L "$ENABLED" ]]; then
  had_enabled=true
fi

ensure_log_directory
ensure_log_file "$ACCESS_LOG"
ensure_log_file "$ERROR_LOG"

/usr/bin/install -m 0644 -o root -g root "$candidate_snapshot" "$candidate_tmp"
mv -Tf "$candidate_tmp" "$AVAILABLE"
committed=true
if [[ "$had_enabled" == false ]]; then
  ln -s ../sites-available/splicr.conf "$ENABLED"
fi

nginx_test_output=$(/usr/sbin/nginx -t 2>&1) || {
  printf '%s\n' "$nginx_test_output" >&2
  false
}
printf '%s\n' "$nginx_test_output"
if [[ "$manages_http" == true ]] && \
  printf '%s\n' "$nginx_test_output" | \
  grep -F "conflicting server name \"${candidate_public_host}\"" | grep -Fq ':80'; then
  echo "The SPLICR hostname already has a port-80 vhost; use SPLICR_HTTP_VHOST_MODE=external or remove the duplicate." >&2
  false
fi
if [[ -n "$candidate_tls_port" ]] && \
  printf '%s\n' "$nginx_test_output" | \
  grep -F "conflicting server name \"${candidate_public_host}\"" | grep -Fq ":${candidate_tls_port}"; then
  echo "The SPLICR hostname already has a TLS vhost on port $candidate_tls_port; refusing an ignored or ambiguous deployment." >&2
  false
fi
/usr/bin/systemctl reload nginx

committed=false
trap - ERR HUP INT TERM
echo "Installed and reloaded the managed SPLICR NGINX site."
