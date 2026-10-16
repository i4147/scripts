try:
    import http.server as httpserver
    import socketserver
except ImportError:
    import BaseHTTPServer as httpserver
    import SocketServer as socketserver
import argparse
import os
import socket
import subprocess
import sys
import webbrowser

if sys.version_info >= (3, 2):
    from html import escape
else:
    from cgi import escape
try:
    from urllib.request import unquote
except ImportError:
    from urllib2 import unquote
from collections import namedtuple
from typing import Any, Tuple

Node = namedtuple("Node", ["inputs", "rule", "target", "outputs"])


def match_strip(line: str, prefix: str) -> Tuple[bool, str]:
    if not line.startswith(prefix):
        return (False, line)
    return (True, line[len(prefix) :])


def html_escape(text: str) -> str:
    return escape(text, quote=True)


def parse(text: str) -> Node:
    lines = iter(text.split("\n"))
    target = None
    rule = None
    inputs = []
    outputs = []
    try:
        target = next(lines)[:-1]
        line = next(lines)
        match, rule = match_strip(line, "  input: ")
        if match:
            match, line = match_strip(next(lines), "    ")
            while match:
                type = ""
                match, line = match_strip(line, "| ")
                if match:
                    type = "implicit"
                match, line = match_strip(line, "|| ")
                if match:
                    type = "order-only"
                inputs.append((line, type))
                match, line = match_strip(next(lines), "    ")
        match, _ = match_strip(line, "  outputs:")
        if match:
            match, line = match_strip(next(lines), "    ")
            while match:
                outputs.append(line)
                match, line = match_strip(next(lines), "    ")
    except StopIteration:
        pass
    return Node(inputs, rule, target, outputs)


def create_page(body: str) -> str:
    return (
        "<!DOCTYPE html>\n<style>\nbody {\n    font-family: sans;\n    font-size: 0.8em;\n    margin: 4ex;\nh1 {\n    font-weight: normal;\n    font-size: 140%;\n    text-align: center;\n    margin: 0;\nh2 {\n    font-weight: normal;\n    font-size: 120%;\ntt {\n    font-family: WebKitHack, monospace;\n    white-space: nowrap;\n.filelist {\n  -webkit-columns: auto 2;\n</style>\n"
        + body
    )


def generate_html(node: Node) -> str:
    document = ["<h1><tt>%s</tt></h1>" % html_escape(node.target)]
    if node.inputs:
        document.append("<h2>target is built using rule <tt>%s</tt> of</h2>" % html_escape(node.rule))
        if len(node.inputs) > 0:
            document.append("<div class=filelist>")
            for input, type in sorted(node.inputs):
                extra = ""
                if type:
                    extra = " (%s)" % html_escape(type)
                document.append('<tt><a href="?%s">%s</a>%s</tt><br>' % (html_escape(input), html_escape(input), extra))
            document.append("</div>")
    if node.outputs:
        document.append("<h2>dependent edges build:</h2>")
        document.append("<div class=filelist>")
        for output in sorted(node.outputs):
            document.append('<tt><a href="?%s">%s</a></tt><br>' % (html_escape(output), html_escape(output)))
        document.append("</div>")
    return "\n".join(document)


def ninja_dump(target: str) -> Tuple[str, str, int]:
    cmd = [args.ninja_command, "-f", args.f, "-t", "query", target]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    return proc.communicate() + (proc.returncode,)


class RequestHandler(httpserver.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        assert self.path[0] == "/"
        target = unquote(self.path[1:])
        if target == "":
            self.send_response(302)
            self.send_header("Location", "?" + args.initial_target)
            self.end_headers()
            return
        if not target.startswith("?"):
            self.send_response(404)
            self.end_headers()
            return
        target = target[1:]
        ninja_output, ninja_error, exit_code = ninja_dump(target)
        if exit_code == 0:
            page_body = generate_html(parse(ninja_output.strip()))
        else:
            page_body = "<h1><tt>%s</tt></h1>" % html_escape(ninja_error)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(create_page(page_body).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        pass


parser = argparse.ArgumentParser(prog="ninja -t browse")
parser.add_argument("--port", "-p", default=8000, type=int, help="Port number to use (default %(default)d)")
parser.add_argument("--hostname", "-a", default="localhost", type=str, help="Hostname to bind to (default %(default)s)")
parser.add_argument("--no-browser", action="store_true", help="Do not open a webbrowser on startup.")
parser.add_argument("--ninja-command", default="ninja", help="Path to ninja binary (default %(default)s)")
parser.add_argument("-f", default="build.ninja", help="Path to build.ninja file (default %(default)s)")
parser.add_argument("initial_target", default="all", nargs="?", help="Initial target to show (default %(default)s)")


class HTTPServer(socketserver.ThreadingMixIn, httpserver.HTTPServer):
    daemon_threads = True


args = parser.parse_args()
port = args.port
hostname = args.hostname
httpd = HTTPServer((hostname, port), RequestHandler)
try:
    if hostname == "":
        hostname = socket.gethostname()
    print("Web server running on %s:%d, ctl-C to abort..." % (hostname, port))
    print("Web server pid %d" % os.getpid(), file=sys.stderr)
    if not args.no_browser:
        webbrowser.open_new("http://%s:%s" % (hostname, port))
    httpd.serve_forever()
except KeyboardInterrupt:
    print()
