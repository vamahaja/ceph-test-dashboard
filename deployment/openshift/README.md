# Ceph Test Dashboard Deployment on OpenShift

Deploy the Ceph Test Dashboard on OpenShift using plain `Deployment` / `Service` / `Route` manifests and a small `deploy.sh` orchestrator. Configuration is substituted with `envsubst` from a local config file that is not committed.

## Prerequisites

- **OpenShift** cluster and **`oc`** installed; you must be logged in (`oc whoami` succeeds).
- **Permissions** to create namespaces, Deployments, Services, Routes, and ConfigMaps.
- **`envsubst`** — substitutes variables in manifests (usually from the `gettext` package).
- **Container image** built and pushed to a registry the cluster can pull (see [Containerfile](../Containerfile)).

Install `envsubst` on Fedora / CentOS / Rocky:

```bash
sudo dnf install gettext
```

### cert-manager (optional)

By default `deploy.sh` applies [cert.yaml](cert.yaml) (self-signed `ClusterIssuer` + `Certificate`) and creates an edge Route using that TLS secret. This requires **cert-manager** already installed on the cluster (Certificate / ClusterIssuer APIs available).

If cert-manager is not available, or you prefer the default OpenShift router certificate, use `--skip-cert`.

## Directory layout

| File | Purpose |
|------|---------|
| [deploy.sh](deploy.sh) | Orchestrates namespace, optional TLS, ConfigMap, Deployment, Service, Route |
| [dashboard.config.tmpl](dashboard.config.tmpl) | Configuration template (copy to `dashboard.config`, do not commit) |
| [configmap.yaml](configmap.yaml) | Dashboard INI (`paddles`, `pulpito`, `nightly`, `cache`, `overview`, `hardware`) |
| [deployment.yaml](deployment.yaml) | Streamlit app Deployment |
| [service.yaml](service.yaml) | ClusterIP Service on port 8501 |
| [route.yaml](route.yaml) | Edge Route (used with `--skip-cert`) |
| [cert.yaml](cert.yaml) | Optional cert-manager `ClusterIssuer` + `Certificate` |

## Quick start

1. Copy the config template (keep secrets / cluster-specific values out of git):

   ```bash
   cd deployment/openshift && cp ./dashboard.config.tmpl ./dashboard.config
   ```

2. Edit `dashboard.config` and set every variable (see [Configuration](#configuration)).

3. Build and push the image (example using the OpenShift internal registry):

   ```bash
   podman build --format docker -f ../Containerfile -t ceph-test-dashboard:latest ../..
   podman tag ceph-test-dashboard:latest "$DASHBOARD_IMAGE"
   podman push "$DASHBOARD_IMAGE"
   ```

4. Deploy:

   ```bash
   chmod +x ./deploy.sh && ./deploy.sh --dashboard-config ./dashboard.config
   ```

Re-run without issuing a new cert (or when cert-manager is unavailable):

```bash
./deploy.sh --dashboard-config ./dashboard.config --skip-cert
```

## Deploy flow

`deploy.sh` applies resources in this order:

1. **Namespace** — created if missing (`DASHBOARD_NAMESPACE`).
2. **Certificates** (unless `--skip-cert`) — [cert.yaml](cert.yaml) → `ClusterIssuer` + `Certificate`; wait until Ready; create edge Route with `tls.crt` / `tls.key` from secret `ceph-test-dashboard-tls`.
3. **ConfigMap** — [configmap.yaml](configmap.yaml) with Paddles/Pulpito INI values.
4. **Workload** — [deployment.yaml](deployment.yaml) + [service.yaml](service.yaml); wait for rollout.
5. **Route** — custom TLS Route (default) or [route.yaml](route.yaml) when `--skip-cert` is set.

## What gets created

| Resource | Name / location | Purpose |
|----------|-----------------|---------|
| Namespace | `DASHBOARD_NAMESPACE` | Dashboard resources |
| ConfigMap | `ceph-test-dashboard-config` | Mounted INI at `/home/appuser/.config/ceph-test-dashboard.ini` |
| Deployment | `ceph-test-dashboard` | Streamlit on port 8501 |
| Service | `ceph-test-dashboard` | ClusterIP → 8501 |
| Route | `ceph-test-dashboard` | HTTPS edge Route to the Service |
| ClusterIssuer | `CERT_MANAGER_ISSUER_NAME` | Self-signed issuer ([cert.yaml](cert.yaml); skipped with `--skip-cert`) |
| Certificate | `ceph-test-dashboard-certificate` | Issues cert for `DASHBOARD_ROUTE_HOST` |
| Secret | `ceph-test-dashboard-tls` | TLS material from cert-manager (`tls.crt`, `tls.key`) |

## Configuration

Copy [dashboard.config.tmpl](dashboard.config.tmpl) to `dashboard.config`. The deploy script **`source`**s this file; use `KEY=value` lines (no `export` required).

| Variable | Description |
|----------|-------------|
| `DASHBOARD_NAMESPACE` | Namespace for Deployment, Service, Route, ConfigMap |
| `DASHBOARD_ROUTE_HOST` | DNS name on the Route and TLS certificate |
| `DASHBOARD_IMAGE` | Full container image reference |
| `PADDLES_BASE_URL` | Paddles API base URL written into the ConfigMap |
| `PULPITO_BASE_URL` | Pulpito base URL written into the ConfigMap |
| `NIGHTLY_RUN_USER` | Nightly page run-owner filter |
| `CACHE_TTL` | Cache TTL in seconds |
| `CERT_MANAGER_ISSUER_NAME` | `ClusterIssuer` name (required unless `--skip-cert`) |

## CLI options

| Option | Description |
|--------|-------------|
| `--dashboard-config <file>` | **Required.** Path to the shell config file. |
| `--skip-cert` | Do not apply [cert.yaml](cert.yaml); apply [route.yaml](route.yaml) with the default router certificate. |
| `--help` | Show usage and exit. |

## Managing the deployment

Examples assume `oc` is logged in and config is loaded:

```bash
set -a && source ./dashboard.config && set +a
```

**Inspect resources:**

```bash
oc get deployment,svc,route,configmap -n "$DASHBOARD_NAMESPACE" \
  -l app.kubernetes.io/name=ceph-test-dashboard
oc logs -f deployment/ceph-test-dashboard -n "$DASHBOARD_NAMESPACE"
```

**Update config or image:**

Edit `dashboard.config` and re-run:

```bash
./deploy.sh --dashboard-config ./dashboard.config --skip-cert
```

**Remove the dashboard** (certificates / ClusterIssuer may remain if created):

```bash
oc delete deployment,svc,route,configmap -n "$DASHBOARD_NAMESPACE" \
  -l app.kubernetes.io/name=ceph-test-dashboard
```
