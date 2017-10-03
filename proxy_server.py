import re
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import threading
import requests

from bs4 import BeautifulSoup, Comment, Doctype
from bs4.dammit import EntitySubstitution

replace_regex = r"(?P<start>^|\s)(?P<word>\S{6})(?P<end>\s|$)"
subst = r"\g<start>\g<word>™\g<end>"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""


class HabrProxyServer(BaseHTTPRequestHandler):
    habr_protocol = "https://"
    habr_host = "habrahabr.ru"

    def _html_entities(self, string):
        if '&' in string:
            return string
        else:
            return EntitySubstitution.substitute_html(string)

    def _search_words(self, s):
        if s.parent.name in ('script', 'link', 'style', 'meta'):
            return False
        if isinstance(s, Comment) or isinstance(s, Doctype):
            return False
        return s

    def _get_habr_data(self, path, method, headers=None):
        response = requests.request(method, "{0}{1}{2}".format(self.habr_protocol, self.habr_host, path),
                                    allow_redirects=False, headers=headers)
        return response

    def _set_headers(self, response):
        self.send_response(response.status_code)
        for header, value in response.headers.items():
            if header != "Content-Encoding" and header != "Connection":
                self.send_header(header, value)
        self.end_headers()
        self.flush_headers()

    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(HTTPStatus.REQUEST_URI_TOO_LONG)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                # An error code has been sent, just exit
                return

            headers = self.headers
            headers["Host"] = self.habr_host
            headers["Referer"] = self.habr_host
            response = self._get_habr_data(self.path, self.command, headers=headers)
            encoding = response.encoding if response.encoding else "UTF-8"
            content = response.text
            content = content.replace("document.location.href = url;",
                                      'document.location.href = "http://127.0.0.1:9998";')  # If enter via mobile phone
            content = content.replace("https://habrahabr.ru", "http://127.0.0.1:9999")
            content = content.replace("http://habrahabr.ru", "http://127.0.0.1:9999")
            content = content.replace("https://m.habrahabr.ru", "http://127.0.0.1:9998")
            content = content.replace("http://m.habrahabr.ru", "http://127.0.0.1:9998")
            if "text/html" in response.headers["Content-Type"]:
                content = BeautifulSoup(content, 'lxml')
                strings = content.find_all(text=self._search_words)
                for string in strings:
                    string.replaceWith(re.sub(replace_regex, subst, string, 0, re.DOTALL))

            self._set_headers(response)
            if isinstance(content, BeautifulSoup):
                self.wfile.write(content.prettify(encoding=encoding, formatter=self._html_entities))
            elif content is not None:
                self.wfile.write(content.encode(encoding))
            self.connection.close()
        except socket.timeout as e:
            # a read or a write timed out.  Discard this connection
            self.log_error("Request timed out: %r", e)
            self.close_connection = True
            return


class HabrMobileProxyServer(HabrProxyServer):
    habr_host = "m.habrahabr.ru"


def run(server_class=ThreadedHTTPServer, handler_class=HabrProxyServer, handler_mobile_class=HabrMobileProxyServer,
        port=9999, mobile_port=9998):
    server_address = ('', port)
    mobile_server_address = ('', mobile_port)
    httpd = server_class(server_address, handler_class)
    mobile_httpd = server_class(mobile_server_address, handler_mobile_class)
    print('Starting habr proxy at http://{0}:{1}'.format(server_address[0] if server_address[0] else "127.0.0.1", port))
    server_thread = threading.Thread(target=lambda server: server.serve_forever(), args=([httpd]))
    server_thread.start()
    print('Starting mobile habr proxy at http://{0}:{1}'.format(
        mobile_server_address[0] if mobile_server_address[0] else "127.0.0.1", mobile_port))
    mobile_server_thread = threading.Thread(target=lambda server: server.serve_forever(), args=([mobile_httpd]))
    mobile_server_thread.start()


if __name__ == "__main__":
    from sys import argv

    if len(argv) == 2:
        run(port=int(argv[1]), mobile_port=int(argv[2]))
    else:
        run()
