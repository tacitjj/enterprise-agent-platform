#!/usr/bin/env bash

set -euo pipefail

# Purpose: start the authenticated DeerFlow H0 runtime API for local development.
# Scope: H0 only; context, model/tool execution, supervisor and production takeover stay disabled.
# Secrets: only key file paths are accepted; this script never reads or prints private key content.
# Rollback: stop this process and return both H0/client feature flags to false.

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
readonly RUNTIME_ROOT="${REPOSITORY_ROOT}/dianlian-ai-runtime"
readonly DEERFLOW_LOCK_FILE="${RUNTIME_ROOT}/upstream/deerflow.lock.json"

require_environment_value() {
    local variable_name="$1"
    if [[ -z "${!variable_name:-}" ]]; then
        echo "${variable_name} is required for the local DeerFlow H0 runtime." >&2
        exit 2
    fi
}

if [[ "${DIANLIAN_DEERFLOW_H0_ENABLED:-false}" != "true" ]]; then
    echo "DeerFlow H0 is disabled; set DIANLIAN_DEERFLOW_H0_ENABLED=true explicitly." >&2
    exit 2
fi

readonly REQUIRED_VARIABLES=(
    DIANLIAN_DEERFLOW_SOURCE_ROOT
    DIANLIAN_DEERFLOW_DATA_DIR
    DIANLIAN_SERVICE_JWT_KEY_ID
    DIANLIAN_SERVICE_JWT_PUBLIC_KEY_PATH
)
for variable_name in "${REQUIRED_VARIABLES[@]}"; do
    require_environment_value "${variable_name}"
done

if [[ ! "${DIANLIAN_SERVICE_JWT_KEY_ID}" =~ ^[A-Za-z0-9._-]{1,64}$ ]]; then
    echo "DIANLIAN_SERVICE_JWT_KEY_ID is invalid." >&2
    exit 2
fi

if [[ "${DIANLIAN_DEERFLOW_SOURCE_ROOT}" != /* ]]; then
    echo "DIANLIAN_DEERFLOW_SOURCE_ROOT must be an absolute path." >&2
    exit 2
fi
if [[ "${DIANLIAN_DEERFLOW_DATA_DIR}" != /* ]]; then
    echo "DIANLIAN_DEERFLOW_DATA_DIR must be an absolute path." >&2
    exit 2
fi
if [[ "${DIANLIAN_SERVICE_JWT_PUBLIC_KEY_PATH}" != /* \
        || ! -f "${DIANLIAN_SERVICE_JWT_PUBLIC_KEY_PATH}" ]]; then
    echo "DIANLIAN_SERVICE_JWT_PUBLIC_KEY_PATH must reference an existing absolute file." >&2
    exit 2
fi

if ! command -v git >/dev/null 2>&1; then
    echo "git is required to verify the pinned DeerFlow checkout." >&2
    exit 2
fi

uv_bin="${DIANLIAN_UV_BIN:-uv}"
if [[ "${uv_bin}" == */* ]]; then
    if [[ ! -x "${uv_bin}" ]]; then
        echo "DIANLIAN_UV_BIN is not executable." >&2
        exit 2
    fi
elif ! command -v "${uv_bin}" >/dev/null 2>&1; then
    echo "uv is required; install it or set DIANLIAN_UV_BIN." >&2
    exit 2
fi

if [[ ! -d "${DIANLIAN_DEERFLOW_SOURCE_ROOT}" ]]; then
    echo "The configured DeerFlow source root is unavailable." >&2
    exit 2
fi
deerflow_source_root="$(cd "${DIANLIAN_DEERFLOW_SOURCE_ROOT}" && pwd -P)"
expected_commit="$(
    cd "${RUNTIME_ROOT}"
    DIANLIAN_DEERFLOW_LOCK_FILE="${DEERFLOW_LOCK_FILE}" \
        "${uv_bin}" run python -c \
        'import json, os; print(json.load(open(os.environ["DIANLIAN_DEERFLOW_LOCK_FILE"], encoding="utf-8"))["commit"])'
)"
actual_commit="$(git -C "${deerflow_source_root}" rev-parse HEAD 2>/dev/null || true)"
if [[ -z "${expected_commit}" || "${actual_commit}" != "${expected_commit}" ]]; then
    echo "The DeerFlow checkout does not match dianlian-ai-runtime/upstream/deerflow.lock.json." >&2
    exit 2
fi
if [[ ! -d "${deerflow_source_root}/backend/packages/harness" \
        || ! -d "${deerflow_source_root}/backend/packages/extension-api" ]]; then
    echo "The pinned DeerFlow checkout is missing the required sparse packages." >&2
    exit 2
fi

umask 077
mkdir -p "${DIANLIAN_DEERFLOW_DATA_DIR}"
deerflow_data_dir="$(cd "${DIANLIAN_DEERFLOW_DATA_DIR}" && pwd -P)"
if [[ "${deerflow_data_dir}" == "/" \
        || "${deerflow_data_dir}" == "${REPOSITORY_ROOT}" \
        || "${deerflow_data_dir}" == "${RUNTIME_ROOT}" \
        || "${deerflow_data_dir}" == "${deerflow_source_root}" ]]; then
    echo "DIANLIAN_DEERFLOW_DATA_DIR must be a dedicated runtime state directory." >&2
    exit 2
fi

bind_host="${DIANLIAN_AI_RUNTIME_BIND_HOST:-127.0.0.1}"
if [[ "${bind_host}" != "127.0.0.1" ]]; then
    echo "Local DeerFlow H0 only supports DIANLIAN_AI_RUNTIME_BIND_HOST=127.0.0.1." >&2
    exit 2
fi
runtime_port="${DIANLIAN_AI_RUNTIME_PORT:-8091}"
if [[ ! "${runtime_port}" =~ ^[0-9]+$ \
        || "${runtime_port}" -lt 1024 \
        || "${runtime_port}" -gt 65535 ]]; then
    echo "DIANLIAN_AI_RUNTIME_PORT must be an integer between 1024 and 65535." >&2
    exit 2
fi

public_key_ring_json="$(
    cd "${RUNTIME_ROOT}"
    DIANLIAN_LOCAL_KEY_ID="${DIANLIAN_SERVICE_JWT_KEY_ID}" \
    DIANLIAN_LOCAL_PUBLIC_KEY_PATH="${DIANLIAN_SERVICE_JWT_PUBLIC_KEY_PATH}" \
        "${uv_bin}" run python -c \
        'import json, os; print(json.dumps({os.environ["DIANLIAN_LOCAL_KEY_ID"]: os.environ["DIANLIAN_LOCAL_PUBLIC_KEY_PATH"]}, separators=(",", ":")))'
)"

# A shared local .env may also contain database, user-session, model or Java-only
# credentials. H0 does not need them, so do not pass those values to Python.
unset DIANLIAN_DATABASE_URL
unset DIANLIAN_POSTGRES_PASSWORD
unset DIANLIAN_REDIS_PASSWORD
unset DIANLIAN_JWT_SECRET
unset DIANLIAN_MODEL_PROVIDER_KEY
unset DIANLIAN_LOCAL_PASSWORD_HASH
unset DIANLIAN_LOCAL_PLATFORM_PASSWORD_HASH
unset DIANLIAN_SERVICE_JWT_PRIVATE_KEY_PATH

export DIANLIAN_RUNTIME_ROLE=runtime-api
export DIANLIAN_CONTEXT_ENABLED=false
export DIANLIAN_AGENT_ENABLED=false
export DIANLIAN_RUN_SUPERVISOR_ENABLED=false
export DIANLIAN_DEERFLOW_H0_ENABLED=true
export DIANLIAN_DEERFLOW_SOURCE_ROOT="${deerflow_source_root}"
export DIANLIAN_DEERFLOW_DATA_DIR="${deerflow_data_dir}"
export DIANLIAN_SERVICE_JWT_PUBLIC_KEY_RING_JSON="${public_key_ring_json}"
export PYTHONUNBUFFERED=1

cd "${RUNTIME_ROOT}"
echo "Starting local DeerFlow H0 runtime API on 127.0.0.1:${runtime_port}." >&2
exec "${uv_bin}" run --group deerflow-h0 uvicorn --factory dianlian_runtime.app:create_app \
    --host "${bind_host}" \
    --port "${runtime_port}"
