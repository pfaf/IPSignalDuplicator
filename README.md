# IPSignalDuplicator

TCP forwarder with two kinds of connections:

|-----------------------|-----------------------------------------------------------------------------------|
| Role in code          | Meaning                                                                           |
|-----------------------|-----------------------------------------------------------------------------------|
| **RcvClientCon**      | Connection **accepted** on `LISTEN_PORT` (downstream client: telnet, `nc`, etc.). |
| **SendClientConSrvA** | Outbound TCP to **`SERVER_A`** (required **for that session**).                   |
|                       |        Traffic is forwarded both ways; upstream replies return to the Rcv client. |
| **SendClientConSrvB** | Outbound TCP to **`SERVER_B`** (optional). Duplicate send path only;              |
|                       |        upstream replies are **not** relayed back.                                 |
|-----------------------|-----------------------------------------------------------------------------------|

The implementation uses a base class **`SendClientConnection`** for those outbound sockets. Config still uses **`SERVER_A`** / **`SERVER_B`** as `(host, port)` endpoints.

**Session registry:** Each accepted Rcv client gets a row in an in-memory **`SessionRegistry`** (`rcv_addr`, `srv_a` / `srv_b` status strings such as `pending`, `connected`, `failed`, `closed`). Entries are removed when the session ends. For debugging you can call **`snapshot_sessions()`** on the registry from a breakpoint or future admin hook (not exposed on the CLI today).

## Requirements

- Python 3.x  
- Standard library only (`socket`, `select`, `threading`, …)

## Versioning

- **Current version:** `__version__` in `IPSignalDuplicatorServer.py` (printed once at startup).
- **Release notes:** [CHANGELOG.md](CHANGELOG.md) ([Keep a Changelog](https://keepachangelog.com/) style).
- **Source history:** `git log`. Tag releases with `vMAJOR.MINOR.PATCH` when you publish a milestone.

## Configuration

Edit **`config.py`** in the same directory as the server script.

| Setting | Purpose |
|--------|---------|
| `LISTEN_PORT` | Port where **RcvClientCon** sessions are accepted. |
| `SERVER_A` | `(host, port)` for **SendClientConSrvA** — each new Rcv client attempts its own connect; success depends on upstream policy (e.g. single-connection servers). |
| `SERVER_B` | `(host, port)` for **SendClientConSrvB** — optional; reconnects per session if it drops. |
| `CONNECT_TIMEOUT` | Seconds to wait when opening each **SendClientConnection**. |
| `RECONNECT_DELAY` | Delay between **SendClientConSrvB** reconnect attempts in the maintainer thread. |
| `SELECT_TIMEOUT` | Poll interval (seconds) for Rcv + Srv A I/O in the session main loop. |
| `LOG_RESPONSES` | If `True`, log data read from **SendClientConSrvA** under `LOG_DIRECTORY`. |
| `LOG_DIRECTORY`, `LOG_PREFIX` | Log folder and file name prefix (`{LOG_PREFIX}_{LOG_FNAME_TS_FORMAT}.log`). |
| `LOG_TIMESTAMP_FORMAT` | Timestamp format inside each log line. |
| `LOG_FNAME_TS_FORMAT` | Date/time fragment used in the log **file name**. |
| `SEND_DISCONNECT_NOTIFICATION`, `DISCONNECT_MESSAGE` | Optional notice to **RcvClientCon** when **that session’s** SendClientConSrvA drops after having been connected. |
| `DEBUG` | Extra debug prints when `True`. |

Paths like `LOG_DIRECTORY` are resolved relative to the **process working directory**, not necessarily the script folder.

## Running the forwarder

From this project directory:

```bash
python IPSignalDuplicatorServer.py
```

There is **no startup probe** to **`SERVER_A`**. The listener accepts **RcvClientCon** connections immediately; each session then tries **`SendClientConSrvA.connect()`** to **`SERVER_A`**.

- If **`SERVER_A` only allows one connection**, the first Rcv client may succeed and later clients fail that connect step — **only the failing Rcv client** is closed (no global shutdown).
- If **SendClientConSrvA** for a session is lost **after** it connected, **only that RcvClientCon** is torn down (optional `DISCONNECT_MESSAGE`); other sessions keep running.
- If **SendClientConSrvB** drops, that session continues while a background thread retries **`SERVER_B`** using `RECONNECT_DELAY`.

Stop with **Ctrl+C** (all active sessions are signalled to exit).

### Linux service (Debian 12 / systemd)

See **[deploy/debian12/README.md](deploy/debian12/README.md)** for a **systemd** unit (`ip-signal-duplicator.service`), dedicated user setup, and journald logging.

## Testing with `IPTestServer.py`

`IPTestServer.py` is a small interactive TCP server (help / time / echo / quit). Use it as a stand-in for the host behind **`SERVER_A`** or **`SERVER_B`**.

```bash
# Default listen port 9996
python IPTestServer.py

# Custom port (must match SERVER_A or SERVER_B in config.py)
python IPTestServer.py 9999
```

Typical local check:

1. Set `SERVER_A` in `config.py` to `('127.0.0.1', 9996)` (or your chosen port).  
2. Start `python IPTestServer.py` (same port).  
3. Start `python IPSignalDuplicatorServer.py`.  
4. Connect a **RcvClientCon** client to `LISTEN_PORT` (e.g. `nc 127.0.0.1 8010` or telnet).

## License

See [LICENSE](LICENSE) (GPL-3.0).
