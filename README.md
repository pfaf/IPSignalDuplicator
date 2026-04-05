# IPSignalDuplicator

TCP forwarder: it accepts client connections on one port, forwards each client’s traffic to **Server A** (required, bidirectional) and **Server B** (optional, receive-only). Replies from **Server A** are sent back to the client; traffic to **Server B** is not relayed back.

## Requirements

- Python 3.x  
- Standard library only (`socket`, `select`, `threading`, …)

## Configuration

Edit **`config.py`** in the same directory as the server script.

| Setting | Purpose |
|--------|---------|
| `LISTEN_PORT` | Port clients connect to (e.g. telnet/nc). |
| `SERVER_A` | `(host, port)` — must be reachable; responses return to clients. |
| `SERVER_B` | `(host, port)` — optional duplicate sink; reconnects per client if it drops. |
| `CONNECT_TIMEOUT` | Seconds to wait when opening upstream TCP connections. |
| `RECONNECT_DELAY` | Seconds between retries when probing **Server A** after an outage, and between **Server B** reconnect attempts. |
| `SELECT_TIMEOUT` | Main loop poll interval (seconds) for client and Server A I/O. |
| `LOG_RESPONSES` | If `True`, log Server A responses under `LOG_DIRECTORY`. |
| `LOG_DIRECTORY`, `LOG_PREFIX` | Log folder and file name prefix (`{LOG_PREFIX}_{LOG_FNAME_TS_FORMAT}.log`). |
| `LOG_TIMESTAMP_FORMAT` | Timestamp format inside each log line. |
| `LOG_FNAME_TS_FORMAT` | Date/time fragment used in the log **file name**. |
| `SEND_DISCONNECT_NOTIFICATION`, `DISCONNECT_MESSAGE` | Optional message to clients when Server A is lost. |
| `DEBUG` | Extra debug prints when `True`. |

Paths like `LOG_DIRECTORY` are resolved relative to the **process working directory**, not necessarily the script folder.

## Running the forwarder

From this project directory:

```bash
python IPSignalDuplicatorServer.py
```

The process will **not accept clients** until **Server A** answers a short TCP probe. If Server A goes down while clients are connected, **all** client sessions are closed and **new connections are refused** until Server A is reachable again. If **Server B** drops, each client session keeps running and a background thread retries **Server B** using `RECONNECT_DELAY`.

Stop with **Ctrl+C**.

## Testing with `IPTestServer.py`

`IPTestServer.py` is a small interactive TCP server (help / time / echo / quit) useful as a stand-in for **Server A** or **Server B**.

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
4. Connect a client to `LISTEN_PORT` (e.g. `nc 127.0.0.1 8010` or telnet).

## License

See [LICENSE](LICENSE) (GPL-3.0).
