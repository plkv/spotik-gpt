from flask import Flask, redirect, request, session, jsonify
import requests
import os
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = os.urandom(24)

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://spotik-gpt.onrender.com/callback")
TOKENS = {}

SCOPES = "user-read-private playlist-modify-public playlist-modify-private playlist-read-private user-library-read user-top-read"

@app.route("/")
def login():
    query_params = urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES
    })
    return redirect(f"https://accounts.spotify.com/authorize?{query_params}")

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
    access_token = data.get("access_token")
    refresh_token = data.get("refresh_token")

    headers = {"Authorization": f"Bearer {access_token}"}
    me = requests.get("https://api.spotify.com/v1/me", headers=headers).json()
    user_id = me["id"]

    TOKENS[user_id] = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }

    return f"""
    ✅ Авторизация прошла успешно!<br>
    user_id: <b>{user_id}</b><br>
    Можешь теперь использовать GPT-агента!
    """

@app.route("/me/<user_id>")
def get_me(user_id):
    if user_id not in TOKENS:
        return jsonify({"error": "User not authorized"}), 401

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://api.spotify.com/v1/me", headers=headers)
    return jsonify(r.json())

@app.route("/playlists")
def playlists():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in TOKENS:
        return jsonify({"error": "User not authorized"}), 401

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    playlists = []
    url = "https://api.spotify.com/v1/me/playlists"

    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        playlists.extend(data.get("items", []))
        url = data.get("next")

    simplified = [
        {
            "name": p["name"],
            "id": p["id"],
            "tracks": p["tracks"]["total"],
            "owner": p["owner"]["display_name"],
            "followers": p.get("followers", {}).get("total", None)
        } for p in playlists
    ]

    return jsonify(simplified)

@app.route("/top-playlists")
def top_playlists():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in TOKENS:
        return jsonify({"error": "User not authorized"}), 401

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    playlists = []
    url = "https://api.spotify.com/v1/me/playlists"

    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        playlists.extend(data.get("items", []))
        url = data.get("next")

    sorted_playlists = sorted(
        [p for p in playlists if p.get("followers")],
        key=lambda x: x["followers"]["total"], reverse=True
    )

    top_10 = [
        {
            "name": p["name"],
            "id": p["id"],
            "tracks": p["tracks"]["total"],
            "followers": p["followers"]["total"]
        } for p in sorted_playlists[:10]
    ]

    return jsonify(top_10)

@app.route("/saved-playlists")
def saved_playlists():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in TOKENS:
        return jsonify({"error": "User not authorized"}), 401

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    playlists = []
    url = "https://api.spotify.com/v1/me/playlists"

    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        playlists.extend(data.get("items", []))
        url = data.get("next")

    foreign_playlists = [
        {
            "name": p["name"],
            "id": p["id"],
            "owner": p["owner"]["display_name"]
        }
        for p in playlists if p["owner"]["id"] != user_id
    ]

    return jsonify(foreign_playlists)

@app.route("/top-tracks")
def top_tracks():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in TOKENS:
        return jsonify({"error": "User not authorized"}), 401

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "limit": 10,
        "time_range": request.args.get("range", "medium_term")
    }

    r = requests.get("https://api.spotify.com/v1/me/top/tracks", headers=headers, params=params)
    return jsonify(r.json())

@app.route("/duplicates")
def find_duplicates():
    user_id = request.args.get("user_id")
    playlist_id = request.args.get("playlist_id")
    if not user_id or not playlist_id or user_id not in TOKENS:
        return jsonify({"error": "Missing user_id or playlist_id, or user not authorized"}), 400

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    tracks = []
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"

    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        items = data.get("items", [])
        for item in items:
            t = item.get("track")
            if t:
                tracks.append({
                    "name": t["name"],
                    "artist": t["artists"][0]["name"] if t["artists"] else None,
                    "album": t["album"]["name"] if t.get("album") else None,
                    "duration_ms": t.get("duration_ms"),
                    "uri": t.get("uri")
                })
        url = data.get("next")

    seen = set()
    duplicates = []
    for t in tracks:
        key = (t["name"], t["artist"], t["album"], t["duration_ms"])
        if key in seen:
            duplicates.append(t)
        else:
            seen.add(key)

    return jsonify(duplicates)

@app.route("/remove-duplicates", methods=["POST"])
def remove_duplicates():
    data = request.get_json()
    user_id = data.get("user_id")
    playlist_id = data.get("playlist_id")
    uris = data.get("uris", [])

    if not user_id or not playlist_id or not uris or user_id not in TOKENS:
        return jsonify({"error": "Missing user_id, playlist_id, uris or user not authorized"}), 400

    access_token = TOKENS[user_id]["access_token"]
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "tracks": [{"uri": uri} for uri in uris]
    }

    r = requests.delete(f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks", headers=headers, json=payload)

    return jsonify({"status": "removed", "response": r.json()})

@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

@app.route("/shuffle-smart", methods=["POST"])
def shuffle_smart():
    data = request.get_json()
    user_id = data.get("user_id")
    playlist_id = data.get("playlist_id")

    if not user_id or not playlist_id or user_id not in TOKENS:
        return jsonify({"error": "Missing user_id or playlist_id, or user not authorized"}), 400

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"

    all_tracks = []
    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        items = data.get("items", [])
        for item in items:
            track = item.get("track")
            if track:
                all_tracks.append(track["uri"])
        url = data.get("next")

    import random
    random.shuffle(all_tracks)

    delete_payload = {"tracks": [{"uri": uri} for uri in all_tracks]}
    requests.delete(f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks", headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, json=delete_payload)

    add_chunks = [all_tracks[i:i+100] for i in range(0, len(all_tracks), 100)]
    for chunk in add_chunks:
        requests.post(f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks", headers=headers, json={"uris": chunk})

    return jsonify({"status": "shuffled", "total": len(all_tracks)})

@app.route("/shuffle-smart", methods=["POST"])
def shuffle_smart():
    data = request.get_json()
    user_id = data.get("user_id")
    playlist_id = data.get("playlist_id")

    if not user_id or not playlist_id or user_id not in TOKENS:
        return jsonify({"error": "Missing user_id or playlist_id, or user not authorized"}), 400

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"

    all_tracks = []
    while url:
        r = requests.get(url, headers=headers)
        data = r.json()
        items = data.get("items", [])
        for item in items:
            track = item.get("track")
            if track:
                all_tracks.append(track["uri"])
        url = data.get("next")

    import random
    random.shuffle(all_tracks)

    delete_payload = {"tracks": [{"uri": uri} for uri in all_tracks]}
    requests.delete(f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks", headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, json=delete_payload)

    add_chunks = [all_tracks[i:i+100] for i in range(0, len(all_tracks), 100)]
    for chunk in add_chunks:
        requests.post(f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks", headers=headers, json={"uris": chunk})

    return jsonify({"status": "shuffled", "total": len(all_tracks)})

@app.route("/generate-playlist", methods=["POST"])
def generate_playlist():
    data = request.get_json()
    user_id = data.get("user_id")
    seed_uris = data.get("seeds", [])  # могут быть треки, артисты, жанры
    name = data.get("name", "Generated Playlist")

    if not user_id or not seed_uris or user_id not in TOKENS:
        return jsonify({"error": "Missing user_id or seeds, or user not authorized"}), 400

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    rec_params = {
        "limit": 30,
        "seed_tracks": ",".join([s.split(":")[-1] for s in seed_uris if "track" in s])
    }
    r = requests.get("https://api.spotify.com/v1/recommendations", headers=headers, params=rec_params)
    tracks = r.json().get("tracks", [])
    track_uris = [t["uri"] for t in tracks]

    # создаём новый плейлист
    user_profile = requests.get("https://api.spotify.com/v1/me", headers=headers).json()
    create_payload = {
        "name": name,
        "description": "Generated by Spotik GPT",
        "public": False
    }
    new_playlist = requests.post(f"https://api.spotify.com/v1/users/{user_profile['id']}/playlists", headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}, json=create_payload).json()

    # добавляем треки
    requests.post(f"https://api.spotify.com/v1/playlists/{new_playlist['id']}/tracks", headers=headers, json={"uris": track_uris})

    return jsonify({"playlist_id": new_playlist['id'], "name": name, "tracks_added": len(track_uris)})

@app.route("/profile")
def musical_profile():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in TOKENS:
        return jsonify({"error": "User not authorized"}), 401

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    top_artists = requests.get("https://api.spotify.com/v1/me/top/artists?limit=10&time_range=long_term", headers=headers).json().get("items", [])
    top_tracks = requests.get("https://api.spotify.com/v1/me/top/tracks?limit=10&time_range=long_term", headers=headers).json().get("items", [])

    genres = {}
    for artist in top_artists:
        for genre in artist.get("genres", []):
            genres[genre] = genres.get(genre, 0) + 1

    top_genres = sorted(genres.items(), key=lambda x: x[1], reverse=True)[:5]

    profile = {
        "top_genres": [g[0] for g in top_genres],
        "top_artists": [a["name"] for a in top_artists],
        "top_tracks": [t["name"] for t in top_tracks]
    }

    return jsonify(profile)

@app.route("/compare-users")
def compare_users():
    user1 = request.args.get("user1")
    user2 = request.args.get("user2")
    if not user1 or not user2 or user1 not in TOKENS or user2 not in TOKENS:
        return jsonify({"error": "Both users must be authorized"}), 400

    def get_top(user_id):
        access_token = TOKENS[user_id]["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        artists = requests.get("https://api.spotify.com/v1/me/top/artists?limit=20", headers=headers).json().get("items", [])
        tracks = requests.get("https://api.spotify.com/v1/me/top/tracks?limit=20", headers=headers).json().get("items", [])
        genres = {}
        for a in artists:
            for g in a.get("genres", []):
                genres[g] = genres.get(g, 0) + 1
        return {
            "artists": set([a["name"] for a in artists]),
            "tracks": set([t["name"] for t in tracks]),
            "genres": set(genres.keys())
        }

    data1 = get_top(user1)
    data2 = get_top(user2)

    result = {
        "shared_artists": list(data1["artists"] & data2["artists"]),
        "shared_tracks": list(data1["tracks"] & data2["tracks"]),
        "shared_genres": list(data1["genres"] & data2["genres"]),
        "user1_unique_artists": list(data1["artists"] - data2["artists"]),
        "user2_unique_artists": list(data2["artists"] - data1["artists"]),
        "compatibility_score": round(len(data1["artists"] & data2["artists"]) / max(1, len(data1["artists"] | data2["artists"])) * 100, 2)
    }

    return jsonify(result)

@app.route("/recommend-new", methods=["POST"])
def recommend_new():
    data = request.get_json()
    user_id = data.get("user_id")
    seed_uri = data.get("seed_uri")  # альбом, трек или плейлист
    if not user_id or not seed_uri or user_id not in TOKENS:
        return jsonify({"error": "Missing user_id or seed_uri, or user not authorized"}), 400

    access_token = TOKENS[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # Получим все URI из всех плейлистов пользователя
    all_uris = set()
    url = "https://api.spotify.com/v1/me/playlists"
    while url:
        r = requests.get(url, headers=headers).json()
        for pl in r.get("items", []):
            tracks_url = pl["tracks"]["href"]
            while tracks_url:
                tracks_r = requests.get(tracks_url, headers=headers).json()
                for item in tracks_r.get("items", []):
                    track = item.get("track")
                    if track and track.get("uri"):
                        all_uris.add(track["uri"])
                tracks_url = tracks_r.get("next")
        url = r.get("next")

    # Рекомендации от Spotify
    seed_type = seed_uri.split(":")[1]
    seed_id = seed_uri.split(":")[-1]
    rec_url = "https://api.spotify.com/v1/recommendations"

    if seed_type not in ["track", "artist", "genre"]:
        return jsonify({"error": "Unsupported seed type"}), 400

    params = {f"seed_{seed_type}s": seed_id, "limit": 50}
    recs = requests.get(rec_url, headers=headers, params=params).json()

    new_tracks = [t for t in recs.get("tracks", []) if t["uri"] not in all_uris]
    uris = [t["uri"] for t in new_tracks[:30]]

    return jsonify({
        "recommended": uris,
        "excluded_duplicates": len(recs.get("tracks", [])) - len(uris)
    })
