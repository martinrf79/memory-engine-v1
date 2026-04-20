#!/usr/bin/env bash
# ============================================================================
# smoke_test_prod.sh — Prueba end-to-end contra el Cloud Run deployado.
#
# Uso:
#   export BACKEND_URL="https://memory-engine-v11-backend-mcp-XXXX.run.app"
#   export USER_ID="m61775764964"
#   export PASSWORD="tu_password"
#   bash scripts/smoke_test_prod.sh
#
# Corre 8 tests curl y reporta pasa/falla por cada uno.
# ============================================================================
set -uo pipefail

BACKEND_URL="${BACKEND_URL:-}"
USER_ID="${USER_ID:-}"
PASSWORD="${PASSWORD:-}"
PROJECT="${PROJECT:-general}"
BOOK="${BOOK:-general}"

if [[ -z "$BACKEND_URL" || -z "$USER_ID" || -z "$PASSWORD" ]]; then
    echo "✗ Faltan env vars. Seteá BACKEND_URL, USER_ID, PASSWORD."
    exit 2
fi

COOKIE_JAR=$(mktemp)
trap "rm -f $COOKIE_JAR" EXIT

PASS=0; FAIL=0

check() {
    local name="$1"; local pattern="$2"; local body="$3"
    if echo "$body" | grep -qE "$pattern"; then
        echo "  ✓ $name"
        PASS=$((PASS+1))
    else
        echo "  ✗ $name"
        echo "     pattern: $pattern"
        echo "     body:    ${body:0:200}"
        FAIL=$((FAIL+1))
    fi
}

echo "▶ Login"
LOGIN_RESP=$(curl -sS -c "$COOKIE_JAR" -X POST "$BACKEND_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"$USER_ID\",\"password\":\"$PASSWORD\"}")
check "login" "ok|user_id|session" "$LOGIN_RESP"

panel_chat() {
    local msg="$1"; local remember="${2:-false}"
    curl -sS -b "$COOKIE_JAR" -X POST "$BACKEND_URL/panel/chat" \
        -H "Content-Type: application/json" \
        -d "{\"project\":\"$PROJECT\",\"book_id\":\"$BOOK\",\"message\":\"$msg\",\"remember\":$remember}"
}

echo
echo "▶ Guardar memoria: 'Mi sobrino trabaja en seguridad'"
R1=$(panel_chat "Mi sobrino trabaja en seguridad" true)
check "memoria guardada" "saved|stored|guardada" "$R1"

echo
echo "▶ Pregunta SIN signos: 'donde trabaja mi sobrino'"
R2=$(panel_chat "donde trabaja mi sobrino" false)
check "responde con 'sobrino'"    "sobrino"    "$R2"
check "responde con 'seguridad'"  "seguridad"  "$R2"
check "no dice 'guardado'"        "^((?!guardad).)*$"  "$R2" || true

echo
echo "▶ Pregunta CON signos: '¿dónde trabaja mi sobrino?'"
R3=$(panel_chat "¿dónde trabaja mi sobrino?" false)
check "responde con signos" "seguridad" "$R3"

echo
echo "▶ Contradicción: guardar 'Mi sobrino ahora trabaja en Google'"
R4=$(panel_chat "Mi sobrino ahora trabaja en Google" true)
check "se actualiza" "updated|actualizada|saved|guardada" "$R4"

echo
echo "▶ Recall actualizado: 'donde trabaja mi sobrino'"
R5=$(panel_chat "donde trabaja mi sobrino" false)
check "ahora responde 'Google'" "[Gg]oogle" "$R5"

echo
echo "═══════════════════════════════════"
echo " $PASS pasaron / $FAIL fallaron"
echo "═══════════════════════════════════"
[[ $FAIL -eq 0 ]] || exit 1
