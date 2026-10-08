#!/usr/bin/env python3
"""Cleanly close a running gbarecomp runner session.

Sends the TCP `quit` command, which the runtime services at a dispatch
boundary and then exits cleanly: play.sh still archives savestates/traces
and flushes the miss frag, exactly as on a normal close. Use this when the
window-close path hangs (see BRINGUP, section "Close-hang investigation").

Usage: .venv/bin/python tools/quit.py [port]   (default port 19870)
"""
import json
import socket
import sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 19870
with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
    s.sendall(json.dumps({"cmd": "quit"}).encode() + b"\n")
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
print(buf.decode(errors="replace").strip() or "(connection closed)")
