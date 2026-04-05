#!/usr/bin/env python3
"""
Configuration file for TCP Forwarder
Edit this file to change the forwarder behavior
"""

# ============================================================================
# Network Configuration
# ============================================================================

# Port the forwarder listens on (telnet client connects here)
LISTEN_PORT = 8010

# Server A - Bidirectional server (REQUIRED)
# If this server disconnects, the client will be terminated
# SERVER_A = ('192.168.1.10', 23)   # (IP address, port)
SERVER_A = ('192.168.1.94', 9996)   # (IP address, port)

# Server B - Receive-only server (OPTIONAL)
# This server only receives data, responses are ignored
SERVER_B = ('192.168.1.94', 9999)   # (IP address, port)

# ============================================================================
# Connection Settings
# ============================================================================

# Connection timeout in seconds
CONNECT_TIMEOUT = 5

# Delay between TCP reconnect attempts (seconds). Used for Server A recovery probes
# and for Server B reconnection when a client session is active.
RECONNECT_DELAY = 5

# Maximum reconnection attempts for ConnectionManager.reconnect() (0 = unlimited).
# Per-client Server B maintainer uses simple retries with RECONNECT_DELAY.
MAX_RECONNECT_ATTEMPTS = 0

# Main-loop select() timeout in seconds (poll rate for client + Server A I/O).
# Lower = more responsive; higher = less CPU wakeups.
SELECT_TIMEOUT = 0.5

# ============================================================================
# Logging Configuration
# ============================================================================

# Enable/disable logging of Server A responses
LOG_RESPONSES = True

# Directory for log files (will be created if doesn't exist)
LOG_DIRECTORY = "logs"

# Log file prefix (actual file: {LOG_PREFIX}_{timestamp}.log)
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

# Send disconnect notification to client when Server A disconnects
SEND_DISCONNECT_NOTIFICATION = True

# Reserved for future periodic health logic (not used by the main loop today).
HEALTH_CHECK_INTERVAL = 2

# Disconnect notification message
DISCONNECT_MESSAGE = "\r\n[ERROR: Server A disconnected - terminating connection]\r\n"

# Enable debug output (more verbose logging)
DEBUG = True
