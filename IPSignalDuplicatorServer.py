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

# Configuration
LISTEN_PORT = 8010
#SERVER_A = ('192.168.1.6', 8020)  # Bidirectional server
SERVER_A = ('192.168.1.94', 9996)  # Bidirectional server
#SERVER_B = ('192.168.1.94', 8020)   # Receive-only server
SERVER_B = ('192.168.1.94', 9999)   # Receive-only server
CONNECT_TIMEOUT = 5
RECONNECT_DELAY = 5               # Seconds to wait before reconnecting
MAX_RECONNECT_ATTEMPTS = 0        # 0 = unlimited
#LOG_FILE = "/var/log/server_a_responses.log"
LOG_FILE = "/DATA/frouros2/wrk/IPSignalDuplicatorServer-server_a_responses.log"
LOG_RESPONSES = True


#######################################################
### Nothing should be changed below this line normally
#######################################################
import socket
import select
import threading
import sys
import time
import errno
from datetime import datetime

class ConnectionManager:
    def __init__(self, name, address, callback=None, required=False):
        self.name = name
        self.address = address
        self.callback = callback
        self.required = required
        self.sock = None
        self.running = True
        self.reconnect_attempts = 0
        self.lock = threading.Lock()
        
    def connect(self):
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
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
                    self.sock.close()
                except:
                    pass
                self.sock = None
            print(f"🔌 [{self.name}] Disconnected")
    
    def send(self, data):
        """Send data - properly detects broken connections"""
        with self.lock:
            if not self.sock:
                return False
            
            try:
                self.sock.send(data)
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
    
    def disconnect(self):
        with self.lock:
            if self.sock:
                print(f"🔌 [{self.name}] Disconnecting...")
                try:
                    self.sock.close()
                except:
                    pass
                self.sock = None
    
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
    def __init__(self, client_sock, client_addr):
        self.client_sock = client_sock
        self.client_addr = client_addr
        self.running = True
        self.log_file = None
        self.server_a_failed = False  # Track if Server A has failed
        
        self.server_a = ConnectionManager("Server A", SERVER_A, self.handle_server_a_data, True)
        self.server_b = ConnectionManager("Server B", SERVER_B, None, False)
        
        if LOG_RESPONSES:
            try:
                ###timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                timestamp = datetime.now().strftime("%Y%m%d")
                log_filename = f"{LOG_FILE}.{timestamp}"
                self.log_file = open(log_filename, 'ab')
                print(f"[{self.client_addr}] 📝 Logging to {log_filename}")
            except Exception as e:
                print(f"[{self.client_addr}] ⚠️  Could not open log: {e}")
    
    def log_response(self, data):
        if self.log_file:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                self.log_file.write(f"[{timestamp}] From {SERVER_A[0]}:{SERVER_A[1]}\n".encode())
                self.log_file.write(data)
                if not data.endswith(b'\n'):
                    self.log_file.write(b'\n')
                self.log_file.write(b"-" * 80 + b"\n")
                self.log_file.flush()
            except:
                pass
    
    def handle_server_a_data(self, data):
        if data and self.running:
            if LOG_RESPONSES:
                self.log_response(data)
            try:
                self.client_sock.send(data)
            except:
                print(f"[{self.client_addr}] Failed to send to client - client may be gone")
                self.running = False
    
    def run(self):
        """Main forwarding logic"""
        try:
            # Connect to servers
            if not self.server_a.connect():
                print(f"[{self.client_addr}] Failed to connect to Server A - terminating client session")
                self.terminate_client()
                return
            
            self.server_b.connect()
            
            print(f"[{self.client_addr}] Session started - Server A connected")
            
            # Main loop
            while self.running:
                try:
                    # Check client data
                    ready, _, _ = select.select([self.client_sock], [], [], 0.5)
                    
                    if ready:
                        data = self.client_sock.recv(4096)
                        if not data:
                            print(f"[{self.client_addr}] Client disconnected normally")
                            break
                        
                        print(f"[{self.client_addr}] Sending {len(data)} bytes to Server A")
                        
                        # Send to Server A - this will detect broken connection
                        send_success = self.server_a.send(data)
                        if not send_success:
                            print(f"[{self.client_addr}] ❌ Server A connection lost!")
                            print(f"[{self.client_addr}] Terminating client session because Server A is gone")
                            self.terminate_client()
                            break
                        
                        # Send to Server B if connected
                        if self.server_b.is_connected():
                            self.server_b.send(data)
                    
                    # Check for data from Server A
                    server_a_data = self.server_a.receive()
                    if server_a_data is not None:
                        self.handle_server_a_data(server_a_data)
                    elif not self.server_a.is_connected():
                        # Server A disconnected while waiting for data
                        print(f"[{self.client_addr}] ❌ Server A disconnected!")
                        print(f"[{self.client_addr}] Terminating client session because Server A is gone")
                        self.terminate_client()
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
            self.cleanup()
    
    def terminate_client(self):
        """Terminate the client connection"""
        print(f"[{self.client_addr}] 🔴 Terminating client connection...")
        try:
            # Send a message to client before closing (optional)
            try:
                self.client_sock.send(b"\r\n[Server A disconnected - terminating connection]\r\n")
                time.sleep(0.1)
            except:
                pass
            
            # Close the client socket
            self.client_sock.close()
        except:
            pass
        self.running = False
    
    def cleanup(self):
        print(f"[{self.client_addr}] Cleaning up...")
        self.running = False
        self.server_a.stop()
        self.server_b.stop()
        
        if self.log_file:
            try:
                self.log_file.close()
            except:
                pass
        
        # Ensure client socket is closed
        if self.client_sock:
            try:
                self.client_sock.close()
            except:
                pass
        
        print(f"[{self.client_addr}] Cleanup complete")

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind(('0.0.0.0', LISTEN_PORT))
    except Exception as e:
        print(f"Failed to bind to port {LISTEN_PORT}: {e}")
        sys.exit(1)
    
    server.listen(5)
    
    print(f"🚀 TCP Forwarder listening on port {LISTEN_PORT}")
    print(f"📡 Server A: {SERVER_A[0]}:{SERVER_A[1]} (bidirectional - REQUIRED)")
    print(f"📡 Server B: {SERVER_B[0]}:{SERVER_B[1]} (receive-only - OPTIONAL)")
    print(f"⚠️  If Server A disconnects, the client will be terminated")
    print("\nWaiting for telnet clients...\n")
    
    while True:
        try:
            client_sock, client_addr = server.accept()
            print(f"\n📞 Telnet client connected from {client_addr[0]}:{client_addr[1]}")
            
            forwarder = BidirectionalForwarder(client_sock, client_addr)
            thread = threading.Thread(target=forwarder.run)
            thread.daemon = True
            thread.start()
            
        except KeyboardInterrupt:
            print("\n\n🛑 Shutting down...")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
