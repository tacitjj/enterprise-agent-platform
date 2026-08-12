#!/usr/bin/env bash

set -euo pipefail

if ! command -v htpasswd >/dev/null 2>&1; then
    echo "htpasswd is required to generate a BCrypt hash." >&2
    exit 2
fi

read -r -s -p "Local password: " password
printf '\n' >&2
read -r -s -p "Confirm password: " confirmation
printf '\n' >&2

cleanup() {
    password=""
    confirmation=""
}
trap cleanup EXIT

if [[ -z "${password}" || "${password}" != "${confirmation}" ]]; then
    echo "Passwords are empty or do not match." >&2
    exit 2
fi

printf '%s\n' "${password}" | htpasswd -niBC 12 dianlian | cut -d: -f2
