#!/usr/bin/env python3
"""One-time helper: prints the SPOTIFY_REFRESH_TOKEN for the setlist sync. Run on your own computer.

  1. https://developer.spotify.com/dashboard -> Create app. Redirect URI: http://127.0.0.1:8888/callback
     API: "Web API". Copy the Client ID and Client Secret.
  2. SPOTIFY_CLIENT_ID=... SPOTIFY_CLIENT_SECRET=... python3 scripts/spotify_auth.py
  3. Log in in the browser tab that opens; the refresh token is printed here.
Standard library only.
"""
import base64, http.server, json, os, secrets, urllib.parse, urllib.request, webbrowser

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-modify-private playlist-modify-public playlist-read-private"

def main():
    cid, sec = os.environ["SPOTIFY_CLIENT_ID"], os.environ["SPOTIFY_CLIENT_SECRET"]
    state = secrets.token_urlsafe(16)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
        {"client_id": cid, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES, "state": state})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                got.update({k: v[0] for k, v in q.items()})
            self.send_response(200); self.end_headers()
            self.wfile.write(b"Done. You can close this tab and go back to the terminal.")
        def log_message(self, *a): pass

    srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
    print("Opening:", url)
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    if "error" in got:
        raise SystemExit(f"Spotify said: {got['error']}")
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token", method="POST",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data=urllib.parse.urlencode({"grant_type": "authorization_code", "code": got["code"],
                                     "redirect_uri": REDIRECT}).encode())
    tok = json.load(urllib.request.urlopen(req))
    print("\nSPOTIFY_REFRESH_TOKEN =", tok["refresh_token"])

if __name__ == "__main__":
    main()
