#!/usr/bin/env bash
set -Eeuo pipefail

unit_name="echoprofile-extension-mcp.service"
system_unit="/etc/systemd/system/${unit_name}"
user_unit="${HOME}/.config/systemd/user/${unit_name}"
project_unit="${HOME}/Projects/echoprofile/systemd/user/${unit_name}"
backup_unit="${HOME}/.local/state/echoprofile/${unit_name}.system-backup"
python="${HOME}/Projects/echoprofile/.venv/bin/python"

user_service_touched=false
system_service_stopped=false
user_unit_preexisting=false
user_service_was_enabled=false
user_service_was_active=false
system_service_was_enabled=false
system_service_was_active=false

rollback() {
  local status=$?
  if [[ ${status} -eq 0 ]]; then
    return
  fi
  trap - EXIT
  set +e

  if [[ "${user_service_touched}" == true ]]; then
    if [[ "${user_unit_preexisting}" == true ]]; then
      if [[ "${user_service_was_enabled}" == true ]]; then
        systemctl --user enable "${unit_name}"
      else
        systemctl --user disable "${unit_name}"
      fi
      if [[ "${user_service_was_active}" == true ]]; then
        systemctl --user start "${unit_name}"
      else
        systemctl --user stop "${unit_name}"
      fi
    else
      systemctl --user disable --now "${unit_name}"
      if [[ -L "${user_unit}" ]] && [[ "$(readlink -f "${user_unit}")" == "${project_unit}" ]]; then
        rm -f "${user_unit}"
      fi
    fi
    systemctl --user daemon-reload
  fi

  if [[ "${system_service_stopped}" == true ]] && [[ -f "${backup_unit}" ]]; then
    sudo cp "${backup_unit}" "${system_unit}"
    sudo systemctl daemon-reload
    if [[ "${system_service_was_enabled}" == true ]]; then
      sudo systemctl enable "${unit_name}"
    else
      sudo systemctl disable "${unit_name}"
    fi
    if [[ "${system_service_was_active}" == true ]]; then
      sudo systemctl start "${unit_name}"
    else
      sudo systemctl stop "${unit_name}"
    fi
  fi

  echo "Migration failed; rollback attempted. Preserve the backup at ${backup_unit}." >&2
  exit "${status}"
}
trap rollback EXIT

if [[ ! -f "${project_unit}" ]]; then
  echo "Expected merged project unit is missing: ${project_unit}" >&2
  echo "Merge the EchoProfile change and update the main checkout first." >&2
  exit 1
fi

if [[ ! -x "${python}" ]] || ! "${python}" -c 'import echoprofile.mcp_http'; then
  echo "EchoProfile MCP HTTP dependencies are missing from ${python}. Run uv sync in the main checkout first." >&2
  exit 1
fi
if [[ ! -r "${HOME}/.config/echoprofile/extension-token" ]]; then
  echo "EchoProfile extension token is missing or unreadable." >&2
  exit 1
fi
for env_file in "${HOME}/.config/dotfiles/systemd/systemd.env.common" "${HOME}/.config/dotfiles/systemd/systemd.env"; do
  if [[ ! -r "${env_file}" ]]; then
    echo "Required systemd environment file is missing or unreadable: ${env_file}" >&2
    exit 1
  fi
done
if [[ "$(loginctl show-user "${USER}" -p Linger --value)" != yes ]]; then
  echo "User lingering is not enabled; the user service would not reliably start at boot." >&2
  exit 1
fi
if [[ -e "${user_unit}" && ! -L "${user_unit}" ]]; then
  echo "Refusing to replace an existing regular user unit file: ${user_unit}" >&2
  exit 1
fi
if [[ -L "${user_unit}" ]] && [[ "$(readlink -f "${user_unit}")" != "${project_unit}" ]]; then
  echo "Refusing to replace a user unit symlink pointing elsewhere: ${user_unit}" >&2
  exit 1
fi

if [[ -L "${user_unit}" ]]; then
  user_unit_preexisting=true
fi
if systemctl --user is-enabled --quiet "${unit_name}"; then
  user_service_was_enabled=true
fi
if systemctl --user is-active --quiet "${unit_name}"; then
  user_service_was_active=true
fi
if sudo systemctl is-enabled --quiet "${unit_name}"; then
  system_service_was_enabled=true
fi
if sudo systemctl is-active --quiet "${unit_name}"; then
  system_service_was_active=true
fi
if [[ "${user_service_was_active}" == true && "${system_service_was_active}" == true ]]; then
  echo "Both the system and user EchoProfile MCP services are active; refusing to migrate two listeners." >&2
  exit 1
fi

mkdir -p "$(dirname "${backup_unit}")" "$(dirname "${user_unit}")"

if sudo test -f "${system_unit}"; then
  if [[ -e "${backup_unit}" ]]; then
    if ! sudo diff -q "${system_unit}" "${backup_unit}" >/dev/null; then
      echo "An existing system-unit backup differs from the installed unit: ${backup_unit}" >&2
      echo "Preserve both files and reconcile the backup manually before migrating." >&2
      exit 1
    fi
  else
    sudo cp "${system_unit}" "${backup_unit}"
    sudo chown "$(id -u):$(id -g)" "${backup_unit}"
  fi
  system_service_stopped=true
  sudo systemctl disable --now "${unit_name}"
  sudo rm "${system_unit}"
  sudo systemctl daemon-reload
fi

user_service_touched=true
ln -sfn "${project_unit}" "${user_unit}"
systemctl --user daemon-reload
systemctl --user enable --now "${unit_name}"
systemctl --user is-active --quiet "${unit_name}"
systemctl --user is-enabled --quiet "${unit_name}"
curl --fail --silent --show-error http://172.17.0.1:8757/health | "${python}" -c 'import json,sys; assert json.load(sys.stdin).get("status") == "ok"'

trap - EXIT
echo
echo "The old system unit backup is at: ${backup_unit}"
echo "The EchoProfile user service now owns ${unit_name}."
