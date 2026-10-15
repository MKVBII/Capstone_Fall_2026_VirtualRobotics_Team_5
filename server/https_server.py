import http.server
import ssl
 
PORT = 8443          # 8443 is the conventional "HTTPS on a nonstandard port"
CERT = "cert.pem"
KEY = "key.pem"
 
# SimpleHTTPRequestHandler is the same handler `python3 -m http.server` uses:
# it serves files from whatever directory you launch this from.
server = http.server.HTTPServer(("0.0.0.0", PORT),
                                http.server.SimpleHTTPRequestHandler)
 
# Build a TLS context and load the self-signed certificate into it.
# PROTOCOL_TLS_SERVER means "act as the server side of a TLS connection".
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(certfile=CERT, keyfile=KEY)
 
# Wrap the plain TCP socket in TLS. Everything above this line is ordinary
# HTTP; the wrapping is what makes it HTTPS.
server.socket = context.wrap_socket(server.socket, server_side=True)
 
print(f"serving HTTPS on port {PORT}")
server.serve_forever()