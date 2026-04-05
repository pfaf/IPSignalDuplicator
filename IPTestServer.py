#!/usr/bin/env python3
import argparse
import socket
import sys
import time

HOST = "0.0.0.0"
DEFAULT_PORT = 9996  # above 1024 avoids needing sudo on Unix


def main():
    parser = argparse.ArgumentParser(
        description="Simple TCP test server (e.g. mock Server A or Server B for IPSignalDuplicator)."
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=DEFAULT_PORT,
        help=f"TCP listen port (default: {DEFAULT_PORT})",
    )
    args = parser.parse_args()
    PORT = args.port
    if not (1 <= PORT <= 65535):
        print(f"Invalid port {PORT}: must be 1–65535", file=sys.stderr)
        sys.exit(1)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    
    print(f"🎯 Test Server A listening on port {PORT}")
    print("Waiting for connections...\n")
    
    while True:
        client, addr = server.accept()
        print(f"📞 Server A: Client connected from {addr}")
        try:
            try:
                client.sendall(b"Welcome to Test Server A\r\n")
                client.sendall(b"Type 'help' for commands\r\n> ")
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                print(f"Server A: peer closed before banner (e.g. health probe): {e!r}")
            else:
                while True:
                    try:
                        data = client.recv(1024)
                        if not data:
                            break

                        message = data.decode().strip()
                        print(f"Server A received: {message}")

                        if message.lower() == "help":
                            response = "Commands: help, time, echo, quit\r\n> "
                        elif message.lower() == "time":
                            response = f"Server time: {time.ctime()}\r\n> "
                        elif message.lower().startswith("echo"):
                            response = f"You said: {message[5:]}\r\n> "
                        elif message.lower() == "quit":
                            response = "Goodbye!\r\n"
                            client.sendall(response.encode())
                            break
                        else:
                            response = f"Unknown command: {message}\r\n> "

                        client.sendall(response.encode())

                    except (BrokenPipeError, ConnectionResetError, OSError) as e:
                        print(f"Server A I/O error: {e!r}")
                        break
                    except Exception as e:
                        print(f"Server A error: {e}")
                        break
        finally:
            try:
                client.close()
            except OSError:
                pass
        print("Server A: Client disconnected\n")

if __name__ == '__main__':
    main()