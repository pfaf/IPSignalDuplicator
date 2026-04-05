# IPSignalDuplicator on Debian 12 (systemd)

This folder contains a **systemd** unit so the forwarder runs in the background and restarts on failure.

## Prerequisites

- Debian 12 (or similar) with **Python 3** (`/usr/bin/python3`).
- Repository copied to a fixed path, e.g. `/opt/ip-signal-duplicator`.
- Edit **`config.py`** in that directory (`LISTEN_PORT`, `SERVER_A`, `SERVER_B`, logging paths, etc.).

`LOG_DIRECTORY` in `config.py` is relative to the process **working directory**. With the unit below, **`WorkingDirectory`** is the repo root, so e.g. `logs/` means `/opt/ip-signal-duplicator/logs/`. Ensure that directory exists and is writable by the service user, or use an absolute `LOG_DIRECTORY`.

## 1. Dedicated user (recommended)

```bash
sudo mkdir -p /opt/ip-signal-duplicator
# Copy or clone the project into /opt/ip-signal-duplicator

sudo useradd --system \
  --home /opt/ip-signal-duplicator \
  --shell /usr/sbin/nologin \
  ipdup

sudo chown -R ipdup:ipdup /opt/ip-signal-duplicator
```

## 2. Install the unit

Edit **`ip-signal-duplicator.service`** if your install path or user name differs from:

- `WorkingDirectory=/opt/ip-signal-duplicator`
- `ExecStart=/usr/bin/python3 /opt/ip-signal-duplicator/IPSignalDuplicatorServer.py`
- `User=ipdup` / `Group=ipdup`

If **`LISTEN_PORT`** is **below 1024**, uncomment **`AmbientCapabilities`** and **`CapabilityBoundingSet`** in the unit (or use a port ≥ 1024).

Then:

```bash
sudo install -m 644 ip-signal-duplicator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ip-signal-duplicator.service
sudo systemctl start ip-signal-duplicator.service
```

## 3. Optional environment file

```bash
sudo cp ip-signal-duplicator.env.example /etc/default/ip-signal-duplicator
sudo chmod 644 /etc/default/ip-signal-duplicator
sudo systemctl restart ip-signal-duplicator.service
```

## 4. Check status and logs

```bash
sudo systemctl status ip-signal-duplicator.service
journalctl -u ip-signal-duplicator.service -f
```

## 5. Firewall

Allow **`LISTEN_PORT`** (and any upstream rules you need), e.g. with `nftables` or `ufw`, depending on your host.
