#!/usr/bin/env bash
set -euo pipefail

unit_name="echoprofile-extension-mcp.service"
system_unit="/etc/systemd/system/${unit_name}"
user_unit="${HOME}/.config/systemd/user/${unit_name}"
project_unit="${HOME}/Projects/echoprofile/systemd/user/${unit_name}"
backup_unit="${HOME}/.local/state/echoprofile/${unit_name}.system-backup"

if [[ ! -f "${project_unit}" ]]; then
  echo "Expected merged project unit is missing: ${project_unit}" >&2
  echo "Merge the EchoProfile change and update the main checkout first." >&2
  exit 1
fi

mkdir -p "$(dirname "${backup_unit}")"
mkdir -p "$(dirname "${user_unit}")"

if sudo test -f "${system_unit}"; then
  sudo cp -n "${system_unit}" "${backup_unit}"
  sudo chown "$(id -u):$(id -g)" "${backup_unit}"
  sudo systemctl disable --now "${unit_name}"
  sudo rm "${system_unit}"
  sudo systemctl daemon-reload
fi

ln -sfn "${project_unit}" "${user_unit}"
systemctl --user daemon-reload
systemctl --user enable --now "${unit_name}"
systemctl --user status "${unit_name}" --no-pager
curl --fail --silent --show-error http://172.17.0.1:8757/health

echo
echo "The old system unit backup is at: ${backup_unit}"
echo "The user service now owns ${unit_name}."
