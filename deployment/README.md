# Deployment

Deploy the Ceph Test Dashboard as a Podman container.

## Prerequisites

- [Podman](https://podman.io/getting-started/installation) installed
- [Podman Compose](https://github.com/containers/podman-compose) installed

## Deployment Steps

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
    ttl = 3600
    ```

2. **Build the container image**

    ```sh
    podman build --format docker -f deployment/Containerfile -t ceph-test-dashboard:latest .
    ```

3. **Start the service**

    ```sh
    podman-compose -f deployment/podman-compose.yaml up -d
    ```

    To use a custom config file path or port:

    ```sh
    CONFIG_FILE=/path/to/config.ini DASHBOARD_PORT=9000 \
      podman-compose -f deployment/podman-compose.yaml up -d
    ```

4. **Verify the deployment**

    ```sh
    podman-compose -f deployment/podman-compose.yaml ps
    ```

    The container should show "Up" status.

5. **Access the dashboard**

    Open your browser at `http://localhost:8501` (or the custom port you set).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONFIG_FILE` | `~/.config/ceph-test-dashboard.ini` | Path to the config file on the host |
| `DASHBOARD_PORT` | `8501` | Host port to expose the dashboard on |

## Managing the Service

Stop:

```sh
podman-compose -f deployment/podman-compose.yaml down
```

View logs:

```sh
podman-compose -f deployment/podman-compose.yaml logs -f
```