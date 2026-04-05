# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.1] - 2026-04-05

### Changed

- **SendClientConSrvB:** detect peer disconnect via `select` + non-blocking inbound probe; update session status and wake reconnect thread.
- **SendClientConSrvB:** on RcvClientCon data, inline connect/send retries (`SRV_B_INLINE_*`), then a bounded pending queue flushed when SERVER_B returns; maintainer uses shorter waits when data is pending.

## [0.7.0] - 2026-04-05

Pre-release: not yet validated in production; semantic **0.x** until real-world testing stabilizes the behaviour.

### Added

- `CHANGELOG.md` and module `__version__` in `IPSignalDuplicatorServer.py`.
- `SessionRegistry` with per-session `srv_a` / `srv_b` status and `snapshot_sessions()` for debugging.
- `RcvClientCon`, `SendClientConnection`, `SendClientConSrvA`, `SendClientConSrvB` naming.
- `IPTestServer.py` for local testing; optional CLI listen port.
- `config.py`-driven settings (paths, timeouts, logging formats, disconnect message).

### Changed

- **Per-session upstream TCP:** each `RcvClientCon` opens its own `SendClientConSrvA` / `SendClientConSrvB`; no startup probe to `SERVER_A`.
- If `SERVER_A` rejects extra connections (e.g. single-client server), only that `RcvClientCon` is dropped.
- If `SendClientConSrvA` drops after connect, only that session ends; other sessions continue.
- `SendClientConSrvB` reconnects in a per-session background thread (`RECONNECT_DELAY`).
- Resilience: `threading.RLock` on send paths, `sendall`, `SELECT_TIMEOUT`, shared log write lock, probe/drain behaviour removed with per-session connect.

### Removed

- Global “crisis” / accept-pause when `SERVER_A` was down (`ServiceController` / startup probe flow).

## [0.6.2] - 2026-04-02

- Work on disconnection and termination behaviour.

## [0.6.1] - 2026-04-02

- Handle broken pipe / send errors toward upstream A.

## [0.6.0] - 2026-04-02

- Logging and tracing for SERVER_A responses.

## [0.5.0] - 2026-04-02

- Initial script version for lab testing (upstream “Server A / B” forwarder concept).

---

**Earlier detail** lived only in Git commit messages and the old file header; those lines are summarized above. For day-to-day history, prefer `git log`.

**Releases:** tag significant versions in Git, e.g. `git tag -a v0.7.0 -m "Release 0.7.0"` and push tags.
