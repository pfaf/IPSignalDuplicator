#!/usr/bin/env python3
"""
Configuration for IPSignalDuplicatorServer.

Code naming (see README):
  RcvClientCon          — accepted TCP client on LISTEN_PORT
  SendClientConSrvA/B   — outbound connections to SERVER_A / SERVER_B
"""

# ============================================================================
# Network Configuration
# ============================================================================

# Port on which the forwarder accepts RcvClientCon connections (telnet, nc, etc.)
LISTEN_PORT = 8010

# Upstream endpoint for SendClientConSrvA (REQUIRED per session, bidirectional).
# Each new RcvClientCon tries its own TCP connect here. If connect fails (busy host,
# single-connection server, etc.), only that RcvClientCon is dropped; others are unaffected.
# SERVER_A = ('192.168.1.10', 23)   # (IP address, port)
SERVER_A = ('192.168.1.94', 9996)   # (IP address, port)

# Upstream endpoint for SendClientConSrvB (OPTIONAL, receive-only duplicate path).
# Responses from this path are not relayed back to RcvClientCon.
SERVER_B = ('192.168.1.94', 9999)   # (IP address, port)

# ============================================================================
# Connection Settings
# ============================================================================

# Seconds to wait when opening each SendClientConnection (TCP connect).
CONNECT_TIMEOUT = 5

# Seconds between SendClientConSrvB reconnect attempts in the per-session maintainer thread.
RECONNECT_DELAY = 5

# Maximum reconnection attempts for SendClientConnection.reconnect() (0 = unlimited).
# The SendClientConSrvB maintainer uses simple connect retries with RECONNECT_DELAY.
MAX_RECONNECT_ATTEMPTS = 0

# Main forwarder loop: select() timeout in seconds (poll rate for RcvClientCon +
# SendClientConSrvA I/O). Lower = more responsive; higher = less CPU wakeups.
SELECT_TIMEOUT = 0.5

# ============================================================================
# Logging Configuration
# ============================================================================

# If True, log bytes received from SendClientConSrvA (upstream A) under LOG_DIRECTORY.
LOG_RESPONSES = True

# Directory for log files (will be created if it does not exist)
LOG_DIRECTORY = "logs"

# Log file prefix (actual file: {LOG_PREFIX}_{LOG_FNAME_TS_FORMAT}.log)
LOG_PREFIX = "server_a_responses"

# Timestamp inside each log line (not the file name)
# Format options:
#   "%Y-%m-%d %H:%M:%S.%f"  -> 2024-01-15 14:30:25.123456
#   "%Y-%m-%d %H:%M:%S"     -> 2024-01-15 14:30:25
#   "%H:%M:%S.%f"           -> 14:30:25.123456
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

# Date/time fragment for the log file name: {LOG_PREFIX}_{this}.log
LOG_FNAME_TS_FORMAT = "%Y-%m-%d"

# ============================================================================
# Advanced Settings
# ============================================================================

# If True, send DISCONNECT_MESSAGE to RcvClientCon when that session's SendClientConSrvA is lost
# after it had connected (not used when SendClientConSrvA never connects).
SEND_DISCONNECT_NOTIFICATION = True

# Reserved for future periodic health logic (not used by the main loop today).
HEALTH_CHECK_INTERVAL = 2

# Message sent to RcvClientCon before shutdown when upstream A is unavailable.
DISCONNECT_MESSAGE = "\r\n[ERROR: Server A disconnected - terminating connection]\r\n"

# Enable debug output (more verbose logging)
DEBUG = True
