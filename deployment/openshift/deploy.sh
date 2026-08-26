#!/bin/bash

# Set error handling
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIGMAP_FILE="./configmap.yaml"
DEPLOYMENT_FILE="./deployment.yaml"
SERVICE_FILE="./service.yaml"
ROUTE_FILE="./route.yaml"
CERT_FILE="./cert.yaml"

DASHBOARD_NAME="ceph-test-dashboard"
CERT_MANAGER_TLS_SECRET="ceph-test-dashboard-tls"
POD_READY_TIMEOUT=300s

SKIP_CERT=false

show_help() {
    cat << 'EOF'
Deploy the Ceph Test Dashboard on OpenShift.

Usage: ./deploy.sh [OPTIONS]

Required:
    --dashboard-config <file>   Path to the dashboard configuration file

Optional:
    --skip-cert                 Skip cert-manager Certificate / ClusterIssuer;
                                Route uses the default router certificate
    --help                      Show this help message and exit

Examples:
    ./deploy.sh --dashboard-config ./dashboard.config
    ./deploy.sh --dashboard-config ./dashboard.config --skip-cert
    ./deploy.sh --help
EOF
}

parse_arguments() {
    DASHBOARD_CONFIG=""
    while [[ "$#" -gt 0 ]]; do
        case $1 in
            --dashboard-config)
                DASHBOARD_CONFIG="$2"
                shift 2
                ;;
            --skip-cert)
                SKIP_CERT=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                echo "Unknown parameter passed: $1"
                exit 1
                ;;
        esac
    done

    if [[ -z "${DASHBOARD_CONFIG}" ]]; then
        echo "Error: --dashboard-config <file> is required."
        show_help
        exit 1
    fi
}

load_config() {
    echo "Loading configuration from $DASHBOARD_CONFIG ..."
    if [ -f "$DASHBOARD_CONFIG" ]; then
        # shellcheck source=/dev/null
        set -a
        source "$DASHBOARD_CONFIG"
        set +a
    else
        echo "Error: dashboard config file $DASHBOARD_CONFIG not found!"
        exit 1
    fi

    local required=(
        DASHBOARD_NAMESPACE
        DASHBOARD_ROUTE_HOST
        DASHBOARD_IMAGE
        PADDLES_BASE_URL
        PULPITO_BASE_URL
        NIGHTLY_RUN_USER
    )
    for var in "${required[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            echo "Error: required config variable $var is empty or unset."
            exit 1
        fi
    done

    if [ "$SKIP_CERT" = false ] && [[ -z "${CERT_MANAGER_ISSUER_NAME:-}" ]]; then
        echo "Error: CERT_MANAGER_ISSUER_NAME is required unless --skip-cert is set."
        exit 1
    fi
}

verify_cli() {
    echo "Checking if oc and envsubst are installed ..."
    for tool in oc envsubst; do
        if ! command -v "$tool" &> /dev/null; then
            echo "Error: $tool is not installed."
            exit 1
        fi
    done

    echo "Checking if oc is logged in ..."
    if ! oc whoami &> /dev/null; then
        echo "Error: oc is not logged in."
        exit 1
    fi

    echo "Checking if namespace $DASHBOARD_NAMESPACE exists ..."
    if ! oc get namespace "$DASHBOARD_NAMESPACE" &> /dev/null; then
        echo "Namespace $DASHBOARD_NAMESPACE does not exist, creating it ..."
        oc create namespace "$DASHBOARD_NAMESPACE"
    else
        echo "Namespace $DASHBOARD_NAMESPACE exists, using it ..."
        oc project "$DASHBOARD_NAMESPACE" >/dev/null
    fi
}

apply_manifest() {
    local manifest=$1
    echo "Applying $manifest ..."
    envsubst < "$manifest" | oc apply -f -
}

deploy_certificates() {
    echo "Checking cert-manager CRDs ..."
    if ! oc get crd certificates.cert-manager.io &>/dev/null; then
        echo "Error: cert-manager is not installed (Certificate CRD missing)."
        echo "Install cert-manager, or re-run with --skip-cert."
        exit 1
    fi

    echo "Applying cert-manager issuer and certificate from $CERT_FILE ..."
    apply_manifest "$CERT_FILE"

    echo "Waiting for Certificate to be ready ..."
    oc wait --for=condition=Ready \
        "certificate/ceph-test-dashboard-certificate" \
        --namespace "$DASHBOARD_NAMESPACE" \
        --timeout="$POD_READY_TIMEOUT"
}

apply_route_with_custom_tls() {
    echo "Creating edge Route with TLS from secret '$CERT_MANAGER_TLS_SECRET' ..."
    local tmp
    tmp=$(mktemp -d)
    # shellcheck disable=SC2064
    trap "rm -rf '$tmp'" RETURN

    oc extract "secret/${CERT_MANAGER_TLS_SECRET}" \
        --namespace "$DASHBOARD_NAMESPACE" \
        --keys=tls.crt,tls.key \
        --to="$tmp" \
        --confirm >/dev/null

    oc create route edge "$DASHBOARD_NAME" \
        --namespace "$DASHBOARD_NAMESPACE" \
        --service="$DASHBOARD_NAME" \
        --hostname="$DASHBOARD_ROUTE_HOST" \
        --port=http \
        --cert="$tmp/tls.crt" \
        --key="$tmp/tls.key" \
        --insecure-policy=Redirect \
        --dry-run=client -o yaml | oc apply -f -
}

wait_for_service_ready() {
    echo "Waiting for Service/${DASHBOARD_NAME} to have ready endpoints ..."
    local deadline
    deadline=$((SECONDS + ${POD_READY_TIMEOUT%s}))

    until oc get "service/${DASHBOARD_NAME}" \
        --namespace "$DASHBOARD_NAMESPACE" &>/dev/null; do
        if (( SECONDS >= deadline )); then
            echo "Error: timed out waiting for Service/${DASHBOARD_NAME}."
            exit 1
        fi
        sleep 2
    done

    # Endpoints are ready when at least one pod address is published.
    until oc get "endpoints/${DASHBOARD_NAME}" \
        --namespace "$DASHBOARD_NAMESPACE" \
        -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null | grep -q .; do
        if (( SECONDS >= deadline )); then
            echo "Error: timed out waiting for ready endpoints on Service/${DASHBOARD_NAME}."
            exit 1
        fi
        sleep 2
    done

    echo "Service/${DASHBOARD_NAME} has ready endpoints."
}

deploy_workload() {
    apply_manifest "$CONFIGMAP_FILE"
    apply_manifest "$DEPLOYMENT_FILE"
    apply_manifest "$SERVICE_FILE"

    echo "Waiting for Deployment to become available ..."
    oc rollout status "deployment/${DASHBOARD_NAME}" \
        --namespace "$DASHBOARD_NAMESPACE" \
        --timeout="$POD_READY_TIMEOUT"

    wait_for_service_ready
}

deploy_route() {
    if [ "$SKIP_CERT" = true ]; then
        echo "Applying Route with default router TLS ..."
        apply_manifest "$ROUTE_FILE"
    else
        apply_route_with_custom_tls
    fi
}

get_dashboard_url() {
    echo "Getting the dashboard URL ..."
    local host
    host=$(oc get route "$DASHBOARD_NAME" \
        --namespace "$DASHBOARD_NAMESPACE" \
        -o jsonpath='{.spec.host}')
    echo "Ceph Test Dashboard URL: https://${host}/"
}

echo "Starting Ceph Test Dashboard deployment ..."

parse_arguments "$@"
load_config
verify_cli

if [ "$SKIP_CERT" = false ]; then
    deploy_certificates
else
    echo "Skipping cert-manager resources (--skip-cert)."
fi

deploy_workload
deploy_route

echo "Ceph Test Dashboard deployed successfully."
get_dashboard_url
