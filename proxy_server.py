import re
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

import requests

from bs4 import BeautifulSoup, Comment, Doctype
from bs4.dammit import EntitySubstitution

replace_regex = r"(?P<start>^|\s)(?P<word>\S{6})(?P<end>\s|$)"
subst = r"\g<start>\g<word>™\g<end>"


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""


class HabrProxyServer(BaseHTTPRequestHandler):
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
        response = requests.request(method, "https://habrahabr.ru{0}".format(path), allow_redirects=False, headers=headers)
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
            headers["Host"] = "habrahabr.ru"
            headers["Referer"] = "habrahabr.ru"
            response = self._get_habr_data(self.path, self.command, headers=headers)
            encoding = response.encoding if response.encoding else "UTF-8"
            content = response.text
            content = content.replace("https://habrahabr.ru", "http://127.0.0.1:9999")
            content = content.replace("http://habrahabr.ru", "http://127.0.0.1:9999")
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


def run(server_class=ThreadedHTTPServer, handler_class=HabrProxyServer, port=9999):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print('Starting habr proxy at http://{0}:{1}'.format(server_address[0] if server_address[0] else "127.0.0.1", port))
    httpd.serve_forever()


if __name__ == "__main__":
    from sys import argv

    if len(argv) == 2:
        run(port=int(argv[1]))
    else:
        run()
