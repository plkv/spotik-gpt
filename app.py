from flask import Flask, redirect, request, session, jsonify
import requests
import os
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Spotify App Credentials
CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://spotik-gpt.onrender.com/callback")

SCOPES = "user-read-private playlist-modify-public playlist-modify-private playlist-read-private user-library-read user-top-read"

# Авторизация: перенаправление на Spotify
@app.route("/")
def login():
    query_params = urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES
    })
    return redirect(f"https://accounts.spotify.com/authorize?{query_params}")

# Обработка колбэка
@app.route("/callback")
def callback():
    code = request.args.get("code")
    token_url = "https://accounts.spotify.com/api/token"
    response = requests.post(token_url, data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    })

    data = response.json()
    session["access_token"] = data.get("access_token")
    session["refresh_token"] = data.get("refresh_token")
    return redirect("/me")

# Пример запроса — получаем профиль пользователя
@app.route("/me")
def me():
    access_token = session.get("access_token")
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://api.spotify.com/v1/me", headers=headers)
    return jsonify(r.json())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
