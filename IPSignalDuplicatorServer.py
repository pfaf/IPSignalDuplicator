#!/usr/bin/env python3
#######################################################
### IPSignalDuplicatorServer.py v0.62
#######################################################
### Software to receive text on one port
### and forward it to two servers.
### Responses are returned only from the first server.
###
### Original code from DeepSeek on 2-4-2026
### coordinated by PFaf (pfaf@wisdomsoftware.net)
###
### License GNU GPL v3
###
#######################################################
###
### Instructions:
### Run the forwarder:
###bash
#### Make it executable
###chmod +x /usr/local/bin/bi-forwarder.py
###
#### Run it
###python3 /usr/local/bin/bi-forwarder.py
###
#############################################
###
### Run as a systemd service:
### Create /etc/systemd/system/tcp-forwarder.service:
###
###ini
###[Unit]
###Description=TCP Bidirectional Forwarder
###After=network.target
###
###[Service]
###Type=simple
###ExecStart=/usr/bin/python3 /usr/local/bin/bi-forwarder.py
###Restart=always
###RestartSec=5
###User=nobody
###
###[Install]
###WantedBy=multi-user.target
###Enable and start:
###
###bash
###sudo systemctl daemon-reload
###sudo systemctl enable tcp-forwarder
###sudo systemctl start tcp-forwarder
###
#######################################################
###
### Version History
###
### v0.62 - 20260402 / PFaf + DeepSeek
### - Trying to fix disconnection and termination problems
#######
### v0.61 - 20260402 / PFaf + DeepSeek
### - Added code to handle Broken Pipe Handling "[Server A] Send error: [Errno 32] Broken pipe"
#######
### v0.60 - 20260402 / PFaf + DeepSeek
### - Added bug trace traps and logging for the SERVER_A responses
#######
### v0.50 - 20260402 / PFaf + DeepSeek
### - Initial script version to be tested on Group8 systems
###
#######################################################

"""
TCP forwarder: RcvClientCon (accepted on LISTEN_PORT) ↔ SendClientConSrvA + SendClientConSrvB (optional).

Each RcvClientCon triggers its own connection attempts to SERVER_A / SERVER_B. If SERVER_A only accepts
one connection, additional Rcv clients get SendClientConSrvA connect failures and are dropped alone.

If SendClientConSrvA for a session is lost, only that RcvClientCon is torn down. SendClientConSrvB can
reconnect in the background without dropping the Rcv session.
"""

import socket
import select
import threading
import sys
import time
import errno
import os
from datetime import datetime
from pathlib import Path

# Try to import configuration
try:
    # Add current directory to path for config import
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import config
except ImportError as e:
    print(f"❌ Failed to import config.py: {e}")
    print("   Make sure config.py is in the same directory as this script")
    sys.exit(1)

# Use configuration values
LISTEN_PORT = config.LISTEN_PORT
SERVER_A = config.SERVER_A
SERVER_B = config.SERVER_B
CONNECT_TIMEOUT = config.CONNECT_TIMEOUT
RECONNECT_DELAY = config.RECONNECT_DELAY
MAX_RECONNECT_ATTEMPTS = config.MAX_RECONNECT_ATTEMPTS
LOG_RESPONSES = config.LOG_RESPONSES
LOG_DIRECTORY = config.LOG_DIRECTORY
LOG_PREFIX = config.LOG_PREFIX
LOG_TIMESTAMP_FORMAT = config.LOG_TIMESTAMP_FORMAT
SEND_DISCONNECT_NOTIFICATION = config.SEND_DISCONNECT_NOTIFICATION
DISCONNECT_MESSAGE = config.DISCONNECT_MESSAGE
DEBUG = config.DEBUG
SELECT_TIMEOUT = config.SELECT_TIMEOUT
LOG_FNAME_TS_FORMAT = config.LOG_FNAME_TS_FORMAT

# Serialize writes when multiple clients share the same daily log file
_log_write_lock = threading.Lock()

def debug_print(msg):
    """Print debug messages if DEBUG is enabled"""
    if DEBUG:
        print(f"[DEBUG] {msg}")


class SessionRegistry:
    """Thread-safe list of active sessions: RcvClientCon address + SendClientConSrvA/B status strings."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions = []
        self._forwarders = set()
        self._shutdown = False

    def session_add(self, rcv_addr):
        entry = {
            "rcv_addr": rcv_addr,
            "srv_a": "pending",
            "srv_b": "pending",
        }
        with self._lock:
            self._sessions.append(entry)
        return entry

    def session_update(self, entry, **kwargs):
        with self._lock:
            entry.update(kwargs)

    def session_remove(self, entry):
        with self._lock:
            try:
                self._sessions.remove(entry)
            except ValueError:
                pass

    def register_forwarder(self, fw):
        with self._lock:
            self._forwarders.add(fw)

    def unregister_forwarder(self, fw):
        with self._lock:
            self._forwarders.discard(fw)

    def shutdown_for_exit(self):
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            targets = list(self._forwarders)
        for fw in targets:
            fw.force_shutdown_rcv(notify=False)

    def snapshot_sessions(self):
        """Return a shallow copy of session dicts for display or debugging."""
        with self._lock:
            return [dict(e) for e in self._sessions]


#######################################################
### Nothing should be changed below this line normally
#######################################################


class RcvClientCon:
    """Inbound TCP session accepted from the downstream client (connects to LISTEN_PORT)."""

    __slots__ = ("sock", "addr")

    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr


class SendClientConnection:
    """Outbound TCP connection initiated by this process toward an upstream server (client role)."""

    def __init__(self, name, address, callback=None, required=False):
        self.name = name
        self.address = address
        self.callback = callback
        self.required = required
        self.sock = None
        self.running = True
        self.reconnect_attempts = 0
        self.lock = threading.RLock()
        
    def connect(self):
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except OSError as e:
                    debug_print(f"[{self.name}] close before connect: {e!r}")
                self.sock = None
            
            try:
                print(f"🔌 [{self.name}] Connecting to {self.address[0]}:{self.address[1]}...")
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(CONNECT_TIMEOUT)
                self.sock.connect(self.address)
                self.sock.settimeout(None)
                # Enable TCP keepalive
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                print(f"✅ [{self.name}] Connected successfully")
                self.reconnect_attempts = 0
                return True
            except Exception as e:
                print(f"❌ [{self.name}] Failed to connect: {e}")
                self.sock = None
                return False
    
    def disconnect(self):
        """Close the connection"""
        with self.lock:
            if self.sock:
                try:
                    print(f"🔌 [{self.name}] Trying to disconnect...")
                    self.sock.close()
                except OSError as e:
                    debug_print(f"[{self.name}] disconnect close: {e!r}")
                self.sock = None
            print(f"🔌 [{self.name}] Disconnected")
    
    def send(self, data):
        """Send data - properly detects broken connections"""
        with self.lock:
            if not self.sock:
                return False
            
            try:
                self.sock.sendall(data)
                return True
            except (BrokenPipeError, ConnectionResetError) as e:
                print(f"💔 [{self.name}] Connection lost during send: {e}")
                self.disconnect()
                return False
            except OSError as e:
                if e.errno in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                    print(f"💔 [{self.name}] Connection lost (errno {e.errno}): {e}")
                    self.disconnect()
                    return False
                else:
                    print(f"⚠️  [{self.name}] Send error (errno {e.errno}): {e}")
                    self.disconnect()
                    return False
            except Exception as e:
                print(f"⚠️  [{self.name}] Unexpected send error: {e}")
                self.disconnect()
                return False
    
    def receive(self, buffer_size=4096):
        """Receive data with proper error detection"""
        with self.lock:
            if not self.sock:
                return None
            
            try:
                self.sock.settimeout(0.1)
                data = self.sock.recv(buffer_size)
                self.sock.settimeout(None)
                
                if not data:
                    print(f"🔌 [{self.name}] Remote host closed connection (received 0 bytes)")
                    self.disconnect()
                    return None
                    
                return data
            except socket.timeout:
                return None
            except BlockingIOError:
                return None
            except (BrokenPipeError, ConnectionResetError) as e:
                print(f"💔 [{self.name}] Connection lost during receive: {e}")
                self.disconnect()
                return None
            except OSError as e:
                if e.errno in (errno.ECONNRESET, errno.EPIPE):
                    print(f"💔 [{self.name}] Connection lost (errno {e.errno})")
                    self.disconnect()
                else:
                    print(f"⚠️  [{self.name}] Receive error (errno {e.errno}): {e}")
                    self.disconnect()
                return None
            except Exception as e:
                print(f"⚠️  [{self.name}] Unexpected receive error: {e}")
                self.disconnect()
                return None
    
    def is_connected(self):
        with self.lock:
            return self.sock is not None
    
    
    def reconnect(self):
        if not self.running:
            return False
        
        if MAX_RECONNECT_ATTEMPTS > 0 and self.reconnect_attempts >= MAX_RECONNECT_ATTEMPTS:
            return False
        
        self.reconnect_attempts += 1
        wait_time = min(RECONNECT_DELAY * self.reconnect_attempts, 30)
        print(f"🔄 [{self.name}] Reconnecting in {wait_time}s (attempt {self.reconnect_attempts})...")
        time.sleep(wait_time)
        
        return self.connect()
    
    def stop(self):
        self.running = False
        self.disconnect()


class SendClientConSrvA(SendClientConnection):
    """Send-side client connection to upstream SERVER_A (bidirectional; replies go to RcvClientCon)."""

    def __init__(self, on_upstream_data):
        super().__init__("SendClientConSrvA", SERVER_A, on_upstream_data, True)


class SendClientConSrvB(SendClientConnection):
    """Send-side client connection to upstream SERVER_B (receive-only duplicate path)."""

    def __init__(self):
        super().__init__("SendClientConSrvB", SERVER_B, None, False)


class BidirectionalForwarder:
    def __init__(self, rcv_client_con, session_registry):
        self.rcv_client_con = rcv_client_con
        self.session_registry = session_registry
        self.running = True
        self.log_file = None
        self._force_stopped = False
        self._stop_lock = threading.Lock()

        self.send_client_con_srv_a = SendClientConSrvA(self.handle_send_client_con_srv_a_data)
        self.send_client_con_srv_b = SendClientConSrvB()
        
        if LOG_RESPONSES:
            try:
                log_dir = Path(LOG_DIRECTORY)
                log_dir.mkdir(parents=True, exist_ok=True)
                fname_ts = datetime.now().strftime(LOG_FNAME_TS_FORMAT)
                log_filename = log_dir / f"{LOG_PREFIX}_{fname_ts}.log"
                self.log_file = open(log_filename, 'ab')
                print(f"[{self.rcv_client_con.addr}] 📝 Logging to {log_filename}")
            except Exception as e:
                print(f"[{self.rcv_client_con.addr}] ⚠️  Could not open log: {e}")
    
    def log_response(self, data):
        if self.log_file:
            try:
                with _log_write_lock:
                    entry_ts = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
                    self.log_file.write(f"[{entry_ts}] From {SERVER_A[0]}:{SERVER_A[1]}\n".encode())
                    self.log_file.write(data)
                    if not data.endswith(b'\n'):
                        self.log_file.write(b'\n')
                    self.log_file.write(b"-" * 80 + b"\n")
                    self.log_file.flush()
            except OSError:
                pass
    
    def handle_send_client_con_srv_a_data(self, data):
        if data and self.running:
            if LOG_RESPONSES:
                self.log_response(data)
            try:
                self.rcv_client_con.sock.sendall(data)
            except OSError as e:
                print(f"[{self.rcv_client_con.addr}] Failed to send to RcvClientCon: {e!r}")
                self.running = False

    def force_shutdown_rcv(self, *, notify: bool = False):
        """Wake blocked RcvClientCon I/O (e.g. process shutdown). Optional disconnect line."""
        with self._stop_lock:
            if self._force_stopped:
                return
            self._force_stopped = True
        self.running = False
        try:
            if notify and SEND_DISCONNECT_NOTIFICATION:
                try:
                    self.rcv_client_con.sock.sendall(DISCONNECT_MESSAGE.encode("utf-8", errors="replace"))
                except OSError:
                    pass
            self.rcv_client_con.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _close_rcv_after_failed_srv_a(self):
        """Drop RcvClientCon when SendClientConSrvA never connected (no disconnect banner)."""
        self.running = False
        try:
            self.rcv_client_con.sock.close()
        except OSError:
            pass

    def _maintain_send_client_con_srv_b_loop(self):
        """Background reconnects for SendClientConSrvB without dropping the RcvClientCon session."""
        while self.running:
            if not self.send_client_con_srv_b.is_connected():
                print(f"[{self.rcv_client_con.addr}] 🔄 SendClientConSrvB down — reconnecting to {SERVER_B[0]}:{SERVER_B[1]}...")
                if self.send_client_con_srv_b.connect():
                    print(f"[{self.rcv_client_con.addr}] ✅ SendClientConSrvB connected")
                    self.session_registry.session_update(self._session_entry, srv_b="connected")
                else:
                    time.sleep(RECONNECT_DELAY)
            else:
                time.sleep(min(SELECT_TIMEOUT, 1.0))

    def run(self):
        """Main forwarding logic: one SendClientConSrvA / SendClientConSrvB pair per RcvClientCon."""
        session_entry = self.session_registry.session_add(self.rcv_client_con.addr)
        self._session_entry = session_entry
        self.session_registry.register_forwarder(self)
        try:
            if not self.send_client_con_srv_a.connect():
                self.session_registry.session_update(
                    session_entry,
                    srv_a="failed",
                    srv_b="skipped",
                )
                print(
                    f"[{self.rcv_client_con.addr}] ❌ SendClientConSrvA failed (e.g. SERVER_A busy or "
                    f"single-connection limit) — dropping this RcvClientCon only."
                )
                self._close_rcv_after_failed_srv_a()
                return

            self.session_registry.session_update(session_entry, srv_a="connected")

            self.send_client_con_srv_b.connect()
            self.session_registry.session_update(
                session_entry,
                srv_b="connected" if self.send_client_con_srv_b.is_connected() else "failed",
            )

            b_maintainer = threading.Thread(
                target=self._maintain_send_client_con_srv_b_loop,
                daemon=True,
                name=f"SendClientConSrvB-reconnect-{self.rcv_client_con.addr[0]}:{self.rcv_client_con.addr[1]}",
            )
            b_maintainer.start()

            print(f"[{self.rcv_client_con.addr}] Session started — SendClientConSrvA connected")

            while self.running:
                try:
                    ready, _, _ = select.select([self.rcv_client_con.sock], [], [], SELECT_TIMEOUT)

                    if ready:
                        data = self.rcv_client_con.sock.recv(4096)
                        if not data:
                            print(f"[{self.rcv_client_con.addr}] RcvClientCon disconnected normally")
                            break

                        print(f"[{self.rcv_client_con.addr}] Sending {len(data)} bytes to SendClientConSrvA")

                        send_success = self.send_client_con_srv_a.send(data)
                        if not send_success:
                            print(f"[{self.rcv_client_con.addr}] ❌ SendClientConSrvA connection lost (this session only)")
                            self.session_registry.session_update(session_entry, srv_a="closed")
                            self.terminate_client()
                            break

                        if self.send_client_con_srv_b.is_connected():
                            self.send_client_con_srv_b.send(data)

                    srv_a_data = self.send_client_con_srv_a.receive()
                    if srv_a_data is not None:
                        self.handle_send_client_con_srv_a_data(srv_a_data)
                    elif not self.send_client_con_srv_a.is_connected():
                        print(f"[{self.rcv_client_con.addr}] ❌ SendClientConSrvA disconnected (this session only)")
                        self.session_registry.session_update(session_entry, srv_a="closed")
                        self.terminate_client()
                        break

                except BlockingIOError:
                    continue
                except ConnectionResetError:
                    print(f"[{self.rcv_client_con.addr}] RcvClientCon connection reset")
                    break
                except Exception as e:
                    print(f"[{self.rcv_client_con.addr}] Error: {e}")
                    break

        except Exception as e:
            print(f"[{self.rcv_client_con.addr}] Fatal error: {e}")
        finally:
            self.session_registry.session_update(
                session_entry,
                srv_a="closed",
                srv_b="closed",
            )
            self.session_registry.session_remove(session_entry)
            self.session_registry.unregister_forwarder(self)
            self.cleanup()
    
    def terminate_client(self):
        """Terminate the client connection"""
        print(f"[{self.rcv_client_con.addr}] 🔴 Terminating client connection...")
        try:
            if SEND_DISCONNECT_NOTIFICATION:
                try:
                    self.rcv_client_con.sock.sendall(DISCONNECT_MESSAGE.encode("utf-8", errors="replace"))
                    time.sleep(0.1)
                except OSError:
                    pass
            
            # Close the client socket
            self.rcv_client_con.sock.close()
        except OSError as e:
            debug_print(f"[{self.rcv_client_con.addr}] terminate_client: {e!r}")
        self.running = False
    
    def cleanup(self):
        print(f"[{self.rcv_client_con.addr}] Cleaning up...")
        self.running = False
        self.send_client_con_srv_a.stop()
        self.send_client_con_srv_b.stop()
        
        if self.log_file:
            try:
                self.log_file.close()
            except OSError as e:
                debug_print(f"[{self.rcv_client_con.addr}] log close: {e!r}")
        
        # Ensure client socket is closed
        if self.rcv_client_con.sock:
            try:
                self.rcv_client_con.sock.close()
            except OSError as e:
                debug_print(f"[{self.rcv_client_con.addr}] client close in cleanup: {e!r}")
        
        print(f"[{self.rcv_client_con.addr}] Cleanup complete")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind(("0.0.0.0", LISTEN_PORT))
    except OSError as e:
        print(f"Failed to bind to port {LISTEN_PORT}: {e}")
        sys.exit(1)

    server.listen(5)
    session_registry = SessionRegistry()

    print(f"🚀 TCP Forwarder listening on port {LISTEN_PORT}")
    print(f"📡 SERVER_A {SERVER_A[0]}:{SERVER_A[1]} — each RcvClientCon opens its own SendClientConSrvA")
    print(f"📡 SERVER_B {SERVER_B[0]}:{SERVER_B[1]} — optional; SendClientConSrvB may reconnect per session")
    print("\nWaiting for RcvClientCon connections (no startup probe to SERVER_A)...\n")

    try:
        while True:
            try:
                readable, _, _ = select.select([server], [], [], 1.0)
            except InterruptedError:
                continue
            except KeyboardInterrupt:
                raise
            if not readable:
                continue
            try:
                client_sock, client_addr = server.accept()
            except OSError as e:
                debug_print(f"accept: {e!r}")
                continue

            print(f"\n📞 RcvClientCon from {client_addr[0]}:{client_addr[1]}")
            rcv_client_con = RcvClientCon(client_sock, client_addr)
            forwarder = BidirectionalForwarder(rcv_client_con, session_registry)
            thread = threading.Thread(target=forwarder.run, daemon=True)
            thread.start()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
    finally:
        session_registry.shutdown_for_exit()
        try:
            server.close()
        except OSError as e:
            debug_print(f"listen socket close: {e!r}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
