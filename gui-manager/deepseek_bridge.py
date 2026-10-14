"""Internal authenticated loopback adapter in the Hub process. No installation."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import secrets
import threading
import time
from deepseek_browser import WebError
from deepseek_format import completion_response, messages_to_prompt, sse_frames


class WebBridge:
    def __init__(self, generate, models):
        self.key = secrets.token_hex(32)
        self.generate = generate
        self.models = models
        self.gate = threading.Lock()
        self.closed = threading.Event()
        self.active = None
        bridge = self
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(10)

            def log_message(self, *args):
                pass

            def reply(self, status, value):
                data = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                if status == 429:
                    self.send_header("Retry-After", "5")
                self.end_headers()
                self.wfile.write(data)

            def authorized(self):
                value = self.headers.get("Authorization", "")
                return self.client_address[0] == "127.0.0.1" and not self.headers.get("Origin") and secrets.compare_digest(value.encode("utf-8"), ("Bearer " + bridge.key).encode("ascii"))

            def do_GET(self):
                if not self.authorized():
                    self.reply(401, {"error": {"message": "Hub authorization required"}})
                elif self.path == "/v1/models":
                    self.reply(200, {"object": "list", "data": [{"id": model, "object": "model", "created": 0, "owned_by": "deepseek-web"} for model in bridge.models]})
                else:
                    self.reply(404, {"error": {"message": "Not found"}})

            def do_POST(self):
                if not self.authorized():
                    self.reply(401, {"error": {"message": "Hub authorization required"}})
                    return
                if self.path != "/v1/chat/completions":
                    self.reply(404, {"error": {"message": "Not found"}})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4 * 1024 * 1024 or self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
                        raise ValueError()
                    payload = json.loads(self.rfile.read(size))
                    if not isinstance(payload, dict) or payload.get("model") not in bridge.models:
                        raise ValueError()
                    prompt = messages_to_prompt(payload)
                except (ValueError, TypeError, KeyError, AttributeError):
                    self.reply(400, {"error": {"message": "Invalid request; text-only models and bounded JSON are supported", "type": "invalid_request_error"}})
                    return
                if bridge.closed.is_set():
                    self.reply(503, {"error": {"message": "Hub is shutting down"}})
                    return
                if not bridge.gate.acquire(blocking=False):
                    self.reply(429, {"error": {"message": "DeepSeek Web is busy", "type": "rate_limit_error"}})
                    return
                cancel = threading.Event()
                bridge.active = cancel
                output = queue.Queue(maxsize=1)
                def work():
                    try:
                        answer = bridge.generate(prompt, payload["model"], cancel)
                        output.put((True, completion_response(payload, prompt, answer)))
                    except WebError as error:
                        output.put((False, {"error": {"message": str(error), "type": error.code}}))
                    except Exception:
                        output.put((False, {"error": {"message": "Web chat request failed; check Hub diagnostics", "type": "server_error"}}))
                    finally:
                        bridge.active = None
                        bridge.gate.release()  # Not released while a cancelled worker still runs.
                threading.Thread(target=work, name="deepseek-web-request", daemon=True).start()
                try:
                    if payload.get("stream"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        while True:
                            try:
                                ok, result = output.get(timeout=5)
                                break
                            except queue.Empty:
                                self.wfile.write(b": keep-alive\n\n")
                                self.wfile.flush()
                        frames = sse_frames(result) if ok else ["data: " + json.dumps(result, ensure_ascii=False) + "\n\ndata: [DONE]\n\n"]
                        for frame in frames:
                            self.wfile.write(frame.encode())
                        self.wfile.flush()
                    else:
                        ok, result = output.get(timeout=300)
                        self.reply(200 if ok else 503, result)
                except (OSError, queue.Empty):
                    cancel.set()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, name="deepseek-web-channel", daemon=True)
        self.thread.start()

    def close(self):
        self.closed.set()
        if self.active:
            self.active.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
