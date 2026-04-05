#!/usr/bin/env python3
import socket
import time

HOST = '0.0.0.0'
PORT = 9996  # set this port above 1024 for testing without sudo

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    
    print(f"🎯 Test Server A listening on port {PORT}")
    print("Waiting for connections...\n")
    
    while True:
        client, addr = server.accept()
        print(f"📞 Server A: Client connected from {addr}")
        
        # Send welcome message
        client.send(b"Welcome to Test Server A\r\n")
        client.send(b"Type 'help' for commands\r\n> ")
        
        while True:
            try:
                data = client.recv(1024)
                if not data:
                    break
                
                message = data.decode().strip()
                print(f"Server A received: {message}")
                
                # Send different responses based on input
                if message.lower() == 'help':
                    response = "Commands: help, time, echo, quit\r\n> "
                elif message.lower() == 'time':
                    response = f"Server time: {time.ctime()}\r\n> "
                elif message.lower().startswith('echo'):
                    response = f"You said: {message[5:]}\r\n> "
                elif message.lower() == 'quit':
                    response = "Goodbye!\r\n"
                    client.send(response.encode())
                    break
                else:
                    response = f"Unknown command: {message}\r\n> "
                
                client.send(response.encode())
                
            except Exception as e:
                print(f"Server A error: {e}")
                break
        
        client.close()
        print("Server A: Client disconnected\n")

if __name__ == '__main__':
    main()