from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import time

def run():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is alive!")

    server = HTTPServer(('0.0.0.0', 8080), Handler)
    server.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run, daemon=True).start()
