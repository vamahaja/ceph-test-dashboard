# Deployment

Deploy the Ceph Test Dashboard with Podman locally, or on OpenShift.

## Prerequisites

### Podman (local)

- [Podman](https://podman.io/getting-started/installation) installed
- [Podman Compose](https://github.com/containers/podman-compose) installed

### OpenShift

See [`openshift/README.md`](openshift/README.md) for the full OpenShift flow (`deploy.sh`, config template, cert-manager).

---

## Podman Deployment

1. **Create the config file**

    If you haven't already configured the dashboard for local development, copy the template:

    ```sh
    mkdir -p ~/.config
    cp templates/config.ini.template ~/.config/ceph-test-dashboard.ini
    ```

    Edit `~/.config/ceph-test-dashboard.ini` and set your URLs:

    ```ini
    [paddles]
    base_url = http://paddles.example.com

    [pulpito]
    base_url = http://pulpito.example.com

    [nightly]
    run_user = jenkins-build

    [cache]
    # Report snapshots are shared across sessions for this many minutes.
    refresh_minutes = 60

    [release]
    branches = tentacle, squid, umbrella
    ```

2. **Build the container images**

    Build the dashboard image:
    ```sh
    podman build --format docker -f deployment/podman/Containerfile.dashboard -t ceph-test-dashboard:latest .
    ```

    Build the MCP server image:
    ```sh
    podman build --format docker -f deployment/podman/Containerfile.mcp -t ceph-test-dashboard-mcp:latest .
    ```

3. **Start the service**

    ```sh
    podman-compose -f deployment/podman/podman-compose.yaml up -d
    ```

    To use a custom config file path or port:

    ```sh
    CONFIG_FILE=/path/to/config.ini DASHBOARD_PORT=9000 \
      podman-compose -f deployment/podman/podman-compose.yaml up -d
    ```

4. **Verify the deployment**

    ```sh
    podman-compose -f deployment/podman/podman-compose.yaml ps
    ```

    The container should show "Up" status.

5. **Access the dashboard**

    Open your browser at `http://localhost:8501` (or the custom port you set).

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONFIG_FILE` | `~/.config/ceph-test-dashboard.ini` | Path to the config file on the host |
| `DASHBOARD_PORT` | `8501` | Host port to expose the dashboard on |
| `MCP_PORT` | `8000` | Host port to expose the MCP server on |

### Managing the Service

Stop:

```sh
podman-compose -f deployment/podman/podman-compose.yaml down
```

View logs:

```sh
podman-compose -f deployment/podman/podman-compose.yaml logs -f
```

---

## OpenShift Deployment

OpenShift manifests and the deploy script live under [`openshift/`](openshift/) (`deploy.sh` + config template + `envsubst`).

Quick start:

```sh
cd deployment/openshift
cp ./dashboard.config.tmpl ./dashboard.config
# edit dashboard.config — set namespace, image, route host, paddles/pulpito URLs
chmod +x ./deploy.sh
./deploy.sh --dashboard-config ./dashboard.config
```

Without cert-manager (use the default router certificate):

```sh
./deploy.sh --dashboard-config ./dashboard.config --skip-cert
```

Full details: [`openshift/README.md`](openshift/README.md).
