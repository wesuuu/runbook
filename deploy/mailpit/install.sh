#!/usr/bin/env bash
# Install Mailpit into the helpnow namespace via Helm
set -euo pipefail

NAMESPACE="helpnow"
RELEASE="mailpit"
CHART="jouve/mailpit"
VALUES_FILE="$(dirname "$0")/values.yaml"

# Add Helm repo if not already present
if ! helm repo list 2>/dev/null | grep -q '^jouve'; then
    echo "Adding jouve Helm repo..."
    helm repo add jouve https://jouve.github.io/charts/
fi
helm repo update jouve

# Install or upgrade
echo "Installing Mailpit into namespace '${NAMESPACE}'..."
helm upgrade --install "${RELEASE}" "${CHART}" \
    --namespace "${NAMESPACE}" \
    --values "${VALUES_FILE}" \
    --wait --timeout 120s

echo ""
echo "Mailpit deployed. Checking services..."
kubectl get svc -n "${NAMESPACE}" -l "app.kubernetes.io/name=mailpit"

echo ""
echo "Waiting for external IPs..."
kubectl wait --for=jsonpath='{.status.loadBalancer.ingress}' \
    svc -l "app.kubernetes.io/name=mailpit" \
    -n "${NAMESPACE}" --timeout=60s 2>/dev/null || true

SMTP_IP=$(kubectl get svc -n "${NAMESPACE}" -l "app.kubernetes.io/name=mailpit" \
    -o jsonpath='{.items[?(@.spec.ports[0].port==1025)].status.loadBalancer.ingress[0].ip}' 2>/dev/null)
HTTP_IP=$(kubectl get svc -n "${NAMESPACE}" -l "app.kubernetes.io/name=mailpit" \
    -o jsonpath='{.items[?(@.spec.ports[0].port==8025)].status.loadBalancer.ingress[0].ip}' 2>/dev/null)

echo ""
echo "==================================="
echo "  Mailpit is ready"
echo "  Web UI:  http://${HTTP_IP:-<pending>}:8025"
echo "  SMTP:    ${SMTP_IP:-<pending>}:1025"
echo "==================================="
echo ""
echo "To configure the backend, set in .env:"
echo "  RUNBOOK_SMTP_HOST=${SMTP_IP:-localhost}"
echo "  RUNBOOK_SMTP_PORT=1025"
