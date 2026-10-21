#!/usr/bin/env python3
"""Serve a clearly labeled, synthetic browser preview on loopback. No Docker access."""
from pathlib import Path
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from opiha_apps.catalog import public_catalog

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        path=self.path.split('?',1)[0]
        if path=='/':body=(ROOT/'examples/panel-demo.html').read_bytes();kind='text/html'
        elif path=='/panel.js':body=(ROOT/'homeassistant/custom_components/opiha_apps/panel.js').read_bytes();kind='application/javascript'
        elif path=='/catalog.json':body=json.dumps(public_catalog()).encode();kind='application/json'
        elif path.startswith('/api/opiha_apps/ingress/'):
            body=b'<html><body style="font:20px Arial;padding:40px"><h1>Synthetic embedded app</h1><p>This tests the frame, not ESPHome or Node-RED. No app is running here.</p></body></html>';kind='text/html'
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8787);args=p.parse_args()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Synthetic UI only: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
