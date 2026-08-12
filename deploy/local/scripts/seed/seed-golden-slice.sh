#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
readonly SEED_SQL="${REPOSITORY_ROOT}/deploy/local/sql/seed/golden-slice.sql"
readonly VERIFY_SQL="${REPOSITORY_ROOT}/deploy/local/sql/verify/golden-slice.sql"

if [[ -z "${DIANLIAN_DATABASE_URL:-}" ]]; then
    echo "DIANLIAN_DATABASE_URL is required." >&2
    exit 2
fi

database_url="${DIANLIAN_DATABASE_URL}"
unset DIANLIAN_DATABASE_URL

if [[ -z "${DIANLIAN_LOCAL_USERNAME:-}" ]]; then
    echo "DIANLIAN_LOCAL_USERNAME is required." >&2
    exit 2
fi

local_username="${DIANLIAN_LOCAL_USERNAME}"
unset DIANLIAN_LOCAL_USERNAME
if [[ ! "${local_username}" =~ ^[A-Za-z][A-Za-z0-9._-]{2,63}$ ]]; then
    echo "DIANLIAN_LOCAL_USERNAME must be a 3-64 character local username." >&2
    exit 2
fi

if [[ -z "${DIANLIAN_LOCAL_PASSWORD_HASH:-}" ]]; then
    echo "DIANLIAN_LOCAL_PASSWORD_HASH is required." >&2
    exit 2
fi
local_password_hash="${DIANLIAN_LOCAL_PASSWORD_HASH}"
unset DIANLIAN_LOCAL_PASSWORD_HASH
if [[ ! "${local_password_hash}" =~ ^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$ ]]; then
    echo "DIANLIAN_LOCAL_PASSWORD_HASH must be a BCrypt hash." >&2
    exit 2
fi

if [[ -z "${DIANLIAN_LOCAL_PLATFORM_USERNAME:-}" ]]; then
    echo "DIANLIAN_LOCAL_PLATFORM_USERNAME is required." >&2
    exit 2
fi
platform_username="${DIANLIAN_LOCAL_PLATFORM_USERNAME}"
unset DIANLIAN_LOCAL_PLATFORM_USERNAME
if [[ ! "${platform_username}" =~ ^[A-Za-z][A-Za-z0-9._-]{2,63}$ ]]; then
    echo "DIANLIAN_LOCAL_PLATFORM_USERNAME must be a 3-64 character local username." >&2
    exit 2
fi
local_username_normalized="$(printf '%s' "${local_username}" | tr '[:upper:]' '[:lower:]')"
platform_username_normalized="$(printf '%s' "${platform_username}" | tr '[:upper:]' '[:lower:]')"
if [[ "${platform_username_normalized}" == "${local_username_normalized}" ]]; then
    echo "Enterprise and platform usernames must be different." >&2
    exit 2
fi

if [[ -z "${DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH:-}" ]]; then
    echo "DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH is required." >&2
    exit 2
fi
platform_password_hash="${DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH}"
unset DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH
if [[ ! "${platform_password_hash}" =~ ^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$ ]]; then
    echo "DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH must be a BCrypt hash." >&2
    exit 2
fi

psql_bin="${DIANLIAN_PSQL_BIN:-psql}"
if [[ "${psql_bin}" == */* ]]; then
    if [[ ! -x "${psql_bin}" ]]; then
        echo "DIANLIAN_PSQL_BIN is not executable." >&2
        exit 2
    fi
elif ! command -v "${psql_bin}" >/dev/null 2>&1; then
    echo "psql is required; install it or set DIANLIAN_PSQL_BIN." >&2
    exit 2
fi

cleanup() {
    database_url=""
    local_username=""
    local_password_hash=""
    platform_username=""
    local_username_normalized=""
    platform_username_normalized=""
    platform_password_hash=""
}
trap cleanup EXIT

"${psql_bin}" "${database_url}" \
    -X \
    -v ON_ERROR_STOP=1 \
    -v dianlian_local_username="${local_username}" \
    -v dianlian_local_password_hash="${local_password_hash}" \
    -v dianlian_local_platform_username="${platform_username}" \
    -v dianlian_local_platform_password_hash="${platform_password_hash}" \
    -f "${SEED_SQL}"

"${psql_bin}" "${database_url}" \
    -X \
    -v ON_ERROR_STOP=1 \
    -v dianlian_local_username="${local_username}" \
    -v dianlian_local_platform_username="${platform_username}" \
    -f "${VERIFY_SQL}"

echo "Local Golden Slice seed and smoke verification completed."
