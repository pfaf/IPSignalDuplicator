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
TCP forwarder: clients → Server A (required) + Server B (optional).
If Server A goes down, all clients are closed and new accepts pause until A is reachable again.
If Server B goes down, each client session keeps running while a background thread reconnects B.
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


def probe_server_a_connection():
    """Return True if a new TCP connection to Server A can be established (then closed)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(CONNECT_TIMEOUT)
    try:
        s.connect(SERVER_A)
        return True
    except OSError as e:
        debug_print(f"Server A probe failed: {e!r}")
        return False
    finally:
        try:
            s.close()
        except OSError:
            pass


def wait_until_server_a_available():
    """Block until Server A accepts a probe connection; sleep RECONNECT_DELAY between failures."""
    attempt = 0
    while True:
        attempt += 1
        print(f"🔍 Probing Server A at {SERVER_A[0]}:{SERVER_A[1]} (attempt {attempt})...")
        if probe_server_a_connection():
            print(f"✅ Server A is reachable.")
            return
        print(f"⏳ Server A not reachable; retrying in {RECONNECT_DELAY}s...")
        time.sleep(RECONNECT_DELAY)


class ServiceController:
    """Coordinates accept gating when Server A is down and global client teardown."""

    def __init__(self):
        self._lock = threading.Lock()
        self.accept_allowed = threading.Event()
        self._crisis = False
        self._shutdown = False
        self._forwarders = set()

    def register_forwarder(self, fw):
        with self._lock:
            self._forwarders.add(fw)

    def unregister_forwarder(self, fw):
        with self._lock:
            self._forwarders.discard(fw)

    def begin_accepting_clients(self):
        with self._lock:
            self._crisis = False
            self.accept_allowed.set()

    def on_server_a_unreachable(self):
        with self._lock:
            if self._shutdown or self._crisis:
                return
            self._crisis = True
            self.accept_allowed.clear()
            targets = list(self._forwarders)
        print(
            "⚠️  Server A unreachable — closing all client sessions; "
            "new connections paused until Server A is reachable again."
        )
        for fw in targets:
            fw.force_stop_due_to_server_a()

    def shutdown_for_exit(self):
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self.accept_allowed.clear()
            self._crisis = True
            targets = list(self._forwarders)
        for fw in targets:
            fw.force_stop_due_to_server_a()


#######################################################
### Nothing should be changed below this line normally
#######################################################

class ConnectionManager:
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

class BidirectionalForwarder:
    def __init__(self, client_sock, client_addr, controller):
        self.client_sock = client_sock
        self.client_addr = client_addr
        self.controller = controller
        self.running = True
        self.log_file = None
        self._force_stopped = False
        self._stop_lock = threading.Lock()

        self.server_a = ConnectionManager("Server A", SERVER_A, self.handle_server_a_data, True)
        self.server_b = ConnectionManager("Server B", SERVER_B, None, False)
        
        if LOG_RESPONSES:
            try:
                log_dir = Path(LOG_DIRECTORY)
                log_dir.mkdir(parents=True, exist_ok=True)
                fname_ts = datetime.now().strftime(LOG_FNAME_TS_FORMAT)
                log_filename = log_dir / f"{LOG_PREFIX}_{fname_ts}.log"
                self.log_file = open(log_filename, 'ab')
                print(f"[{self.client_addr}] 📝 Logging to {log_filename}")
            except Exception as e:
                print(f"[{self.client_addr}] ⚠️  Could not open log: {e}")
    
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
    
    def handle_server_a_data(self, data):
        if data and self.running:
            if LOG_RESPONSES:
                self.log_response(data)
            try:
                self.client_sock.sendall(data)
            except OSError as e:
                print(f"[{self.client_addr}] Failed to send to client: {e!r}")
                self.running = False

    def force_stop_due_to_server_a(self):
        """Wake blocked I/O and end session when Server A is lost globally."""
        with self._stop_lock:
            if self._force_stopped:
                return
            self._force_stopped = True
        self.running = False
        try:
            if SEND_DISCONNECT_NOTIFICATION:
                try:
                    self.client_sock.sendall(DISCONNECT_MESSAGE.encode("utf-8", errors="replace"))
                except OSError:
                    pass
            self.client_sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def _maintain_server_b_loop(self):
        """Background reconnects for Server B without dropping the client session."""
        while self.running:
            if not self.server_b.is_connected():
                print(f"[{self.client_addr}] 🔄 Server B down — reconnecting to {SERVER_B[0]}:{SERVER_B[1]}...")
                if self.server_b.connect():
                    print(f"[{self.client_addr}] ✅ Server B connected")
                else:
                    time.sleep(RECONNECT_DELAY)
            else:
                time.sleep(min(SELECT_TIMEOUT, 1.0))

    def run(self):
        """Main forwarding logic"""
        try:
            if not self.server_a.connect():
                print(f"[{self.client_addr}] Failed to connect to Server A — notifying controller")
                self.controller.on_server_a_unreachable()
                self.terminate_client()
                return

            self.controller.register_forwarder(self)
            self.server_b.connect()

            b_maintainer = threading.Thread(
                target=self._maintain_server_b_loop,
                daemon=True,
                name=f"B-reconnect-{self.client_addr[0]}:{self.client_addr[1]}",
            )
            b_maintainer.start()

            print(f"[{self.client_addr}] Session started - Server A connected")

            while self.running:
                try:
                    ready, _, _ = select.select([self.client_sock], [], [], SELECT_TIMEOUT)

                    if ready:
                        data = self.client_sock.recv(4096)
                        if not data:
                            print(f"[{self.client_addr}] Client disconnected normally")
                            break

                        print(f"[{self.client_addr}] Sending {len(data)} bytes to Server A")

                        send_success = self.server_a.send(data)
                        if not send_success:
                            print(f"[{self.client_addr}] ❌ Server A connection lost!")
                            self.controller.on_server_a_unreachable()
                            break

                        if self.server_b.is_connected():
                            self.server_b.send(data)

                    server_a_data = self.server_a.receive()
                    if server_a_data is not None:
                        self.handle_server_a_data(server_a_data)
                    elif not self.server_a.is_connected():
                        print(f"[{self.client_addr}] ❌ Server A disconnected!")
                        self.controller.on_server_a_unreachable()
                        break

                except BlockingIOError:
                    continue
                except ConnectionResetError:
                    print(f"[{self.client_addr}] Client connection reset")
                    break
                except Exception as e:
                    print(f"[{self.client_addr}] Error: {e}")
                    break

        except Exception as e:
            print(f"[{self.client_addr}] Fatal error: {e}")
        finally:
            self.controller.unregister_forwarder(self)
            self.cleanup()
    
    def terminate_client(self):
        """Terminate the client connection"""
        print(f"[{self.client_addr}] 🔴 Terminating client connection...")
        try:
            if SEND_DISCONNECT_NOTIFICATION:
                try:
                    self.client_sock.sendall(DISCONNECT_MESSAGE.encode("utf-8", errors="replace"))
                    time.sleep(0.1)
                except OSError:
                    pass
            
            # Close the client socket
            self.client_sock.close()
        except OSError as e:
            debug_print(f"[{self.client_addr}] terminate_client: {e!r}")
        self.running = False
    
    def cleanup(self):
        print(f"[{self.client_addr}] Cleaning up...")
        self.running = False
        self.server_a.stop()
        self.server_b.stop()
        
        if self.log_file:
            try:
                self.log_file.close()
            except OSError as e:
                debug_print(f"[{self.client_addr}] log close: {e!r}")
        
        # Ensure client socket is closed
        if self.client_sock:
            try:
                self.client_sock.close()
            except OSError as e:
                debug_print(f"[{self.client_addr}] client close in cleanup: {e!r}")
        
        print(f"[{self.client_addr}] Cleanup complete")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind(("0.0.0.0", LISTEN_PORT))
    except OSError as e:
        print(f"Failed to bind to port {LISTEN_PORT}: {e}")
        sys.exit(1)

    server.listen(5)
    controller = ServiceController()

    print(f"🚀 TCP Forwarder listening on port {LISTEN_PORT}")
    print(f"📡 Server A: {SERVER_A[0]}:{SERVER_A[1]} (bidirectional — REQUIRED; accept pauses if down)")
    print(f"📡 Server B: {SERVER_B[0]}:{SERVER_B[1]} (receive-only — reconnects per client without dropping clients)")

    try:
        while True:
            try:
                wait_until_server_a_available()
            except KeyboardInterrupt:
                print("\n\n🛑 Shutting down...")
                break

            controller.begin_accepting_clients()
            print("\nWaiting for clients (Server A is up)...\n")

            while controller.accept_allowed.is_set():
                try:
                    readable, _, _ = select.select([server], [], [], 1.0)
                except InterruptedError:
                    continue
                except KeyboardInterrupt:
                    raise
                if not controller.accept_allowed.is_set():
                    print("⏸️  Pausing accepts — recovering Server A...")
                    break
                if not readable:
                    continue
                try:
                    client_sock, client_addr = server.accept()
                except OSError as e:
                    debug_print(f"accept: {e!r}")
                    continue

                print(f"\n📞 Client connected from {client_addr[0]}:{client_addr[1]}")
                forwarder = BidirectionalForwarder(client_sock, client_addr, controller)
                thread = threading.Thread(target=forwarder.run, daemon=True)
                thread.start()
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
    finally:
        controller.shutdown_for_exit()
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
