# Testing Suite

The purpose of this folder is to hold any test code developed over the course of the project.

# Tests and Instructions

1. Connection Test: Headset to router to RBP and vice versa
   a: Video Path:
      - SSH into the RBP and run the following:
        ///
          cd
          echo "hello from Pi"
          python3 -m http.server 8000
        ///

      - Turn on the Meta Quest and ensure it's on the same network as the RBP (we  used a router)
      - On the Meta Quest's browser, search "http://<IP address of the Pi>:8000"

        You should see the text: "hello from Pi" and something like the following on the RBP's terminal:
        ///
          Serving HTTP on 0.0.0.0 port 8000 (http://0.0.0.0:8000/) ...
          192.168.0.58 - - [29/Sep/2026 19:20:32] "GET / HTTP/1.1" 200 -
          192.168.0.58 - - [29/Sep/2026 19:20:32] code 404, message File not found
          192.168.0.58 - - [29/Sep/2026 19:20:32] "GET /favicon.ico HTTP/1.1" 404 -
        ///

   b: Controls:
