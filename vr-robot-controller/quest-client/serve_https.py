#!/usr/bin/env python3
"""Serves quest-client/ over https:// so the Quest Browser will allow WebXR.

Uses the SAME self-signed cert pi-server/server.py uses for wss:// — the one
docs/setup_guide.md step 6 has you generate into vr-robot-controller/certs/.
Standard library only; nothing to pip install.

Run on the Pi (from anywhere):
    python3 quest-client/serve_https.py            # https://<pi-ip>:8443/
    python3 quest-client/serve_https.py 9443       # different port

Then on the Quest Browser open https://<pi-ip>:8443/ and click through the
one-time "not secure" warning (Advanced -> Proceed).
"""
import functools
import http.server
import os
import ssl
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
CERT_FILE = os.environ.get("PI_SERVER_CERT", os.path.join(REPO_ROOT, "certs", "cert.pem"))
KEY_FILE = os.environ.get("PI_SERVER_KEY", os.path.join(REPO_ROOT, "certs", "key.pem"))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8443

    if not (os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE)):
        sys.exit(
            f"No cert found at {CERT_FILE}.\n"
            "Generate one first, from vr-robot-controller/:\n"
            "  mkdir -p certs\n"
            "  openssl req -x509 -newkey rsa:2048 -nodes -keyout certs/key.pem "
            "-out certs/cert.pem -days 365 -subj /CN=vr-robot"
        )

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT_FILE, KEY_FILE)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    print(f"Serving {HERE} at https://0.0.0.0:{port}/  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
