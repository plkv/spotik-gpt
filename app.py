from flask import Flask, redirect, request, session, jsonify
import requests
import os
import logging
from urllib.parse import urlencode
from functools import wraps
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# Spotify API configuration
CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://spotik-gpt.onrender.com/callback")

# Token storage with expiration
class TokenStorage:
    def __init__(self):
        self._tokens = {}
        self._load_tokens()
    
    def _load_tokens(self):
        try:
            if os.path.exists('tokens.json'):
                with open('tokens.json', 'r') as f:
                    data = json.load(f)
                    for user_id, token_data in data.items():
                        # Convert string timestamp back to datetime
                        token_data['expires_at'] = datetime.fromisoformat(token_data['expires_at'])
                        self._tokens[user_id] = token_data
        except Exception as e:
            logger.error(f"Error loading tokens: {str(e)}")
    
    def _save_tokens(self):
        try:
            data = {}
            for user_id, token_data in self._tokens.items():
                # Convert datetime to string for JSON serialization
                data[user_id] = {
                    'access_token': token_data['access_token'],
                    'refresh_token': token_data['refresh_token'],
                    'expires_at': token_data['expires_at'].isoformat()
                }
            with open('tokens.json', 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving tokens: {str(e)}")
    
    def set_tokens(self, user_id, access_token, refresh_token, expires_in=3600):
        self._tokens[user_id] = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": datetime.now() + timedelta(seconds=expires_in)
        }
        self._save_tokens()
    
    def get_tokens(self, user_id):
        if user_id not in self._tokens:
            return None
        
        tokens = self._tokens[user_id]
        # Refresh token if it's close to expiring (within 5 minutes)
        if datetime.now() + timedelta(minutes=5) >= tokens["expires_at"]:
            new_tokens = self._refresh_token(user_id, tokens["refresh_token"])
            if new_tokens:
                return new_tokens
            return None
        
        return tokens
    
    def _refresh_token(self, user_id, refresh_token):
        try:
            logger.info(f"Refreshing token for user {user_id}")
            response = requests.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET
                }
            )
            response.raise_for_status()
            data = response.json()
            
            self.set_tokens(
                user_id,
                data["access_token"],
                refresh_token,  # Keep the same refresh token
                data.get("expires_in", 3600)
            )
            logger.info(f"Successfully refreshed token for user {user_id}")
            return self._tokens[user_id]
        except Exception as e:
            logger.error(f"Error refreshing token for user {user_id}: {str(e)}")
            return None

token_storage = TokenStorage()

# Decorator for requiring authentication
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = request.args.get("user_id")
        if not user_id:
            return jsonify({"error": "Missing user_id parameter"}), 400
        
        tokens = token_storage.get_tokens(user_id)
        if not tokens:
            return jsonify({"error": "User not authorized"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Error handler
@app.errorhandler(Exception)
def handle_error(error):
    logger.error(f"Unhandled error: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

@app.route("/")
def login():
    query_params = urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": "user-read-private playlist-modify-public playlist-modify-private playlist-read-private user-library-read user-top-read"
    })
    return redirect(f"https://accounts.spotify.com/authorize?{query_params}")

@app.route("/callback")
def callback():
    try:
        code = request.args.get("code")
        error = request.args.get("error")
        
        logger.info(f"Callback received. Code present: {bool(code)}, Error: {error}")
        
        if error:
            logger.error(f"Error in Spotify authorization: {error}")
            return jsonify({"error": f"Authorization failed: {error}"}), 400
            
        if not code:
            logger.error("Missing authorization code")
            return jsonify({"error": "Missing authorization code"}), 400

        logger.info("Requesting access token from Spotify")
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET
            }
        )
        
        if not response.ok:
            logger.error(f"Token request failed: {response.status_code} - {response.text}")
            return jsonify({"error": "Failed to get access token"}), response.status_code
            
        logger.info("Successfully received token response")
        data = response.json()

        headers = {"Authorization": f"Bearer {data['access_token']}"}
        me_response = requests.get("https://api.spotify.com/v1/me", headers=headers)
        
        if not me_response.ok:
            logger.error(f"Failed to get user profile: {me_response.status_code} - {me_response.text}")
            return jsonify({"error": "Failed to get user profile"}), me_response.status_code
            
        me = me_response.json()
        user_id = me["id"]
        logger.info(f"Successfully got user profile for {user_id}")

        token_storage.set_tokens(
            user_id,
            data["access_token"],
            data["refresh_token"],
            data.get("expires_in", 3600)
        )
        logger.info("Tokens stored successfully")

        return f"""
        ✅ Authorization successful!<br>
        user_id: <b>{user_id}</b><br>
        You can now use the GPT agent!
        """
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during callback: {str(e)}")
        return jsonify({"error": "Network error during authorization"}), 503
    except Exception as e:
        logger.error(f"Unexpected error in callback: {str(e)}")
        return jsonify({"error": "Authorization failed"}), 500

@app.route("/health")
def health():
    return jsonify({"status": "healthy"})

@app.route("/playlists")
@require_auth
def playlists():
    try:
        user_id = request.args.get("user_id")
        tokens = token_storage.get_tokens(user_id)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        
        playlists = []
        url = "https://api.spotify.com/v1/me/playlists"

        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
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
    except Exception as e:
        logger.error(f"Error getting playlists: {str(e)}")
        return jsonify({"error": "Failed to get playlists"}), 500

@app.route("/me/<user_id>")
def get_me(user_id):
    if user_id not in token_storage._tokens:
        return jsonify({"error": "User not authorized"}), 401

    access_token = token_storage._tokens[user_id]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get("https://api.spotify.com/v1/me", headers=headers)
    return jsonify(r.json())

@app.route("/top-playlists")
def top_playlists():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in token_storage._tokens:
        return jsonify({"error": "User not authorized"}), 401

    access_token = token_storage._tokens[user_id]["access_token"]
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
    if not user_id or user_id not in token_storage._tokens:
        return jsonify({"error": "User not authorized"}), 401

    access_token = token_storage._tokens[user_id]["access_token"]
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
    if not user_id or user_id not in token_storage._tokens:
        return jsonify({"error": "User not authorized"}), 401

    access_token = token_storage._tokens[user_id]["access_token"]
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
    if not user_id or not playlist_id or user_id not in token_storage._tokens:
        return jsonify({"error": "Missing user_id or playlist_id, or user not authorized"}), 400

    access_token = token_storage._tokens[user_id]["access_token"]
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
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        playlist_id = data.get("playlist_id")

        if not user_id or not playlist_id:
            return jsonify({"error": "Missing user_id or playlist_id"}), 400

        tokens = token_storage.get_tokens(user_id)
        if not tokens:
            return jsonify({"error": "User not authorized"}), 401

        headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "Content-Type": "application/json"
        }

        # Get all tracks in the playlist
        tracks = []
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            tracks.extend(data.get("items", []))
            url = data.get("next")

        logger.info(f"Found {len(tracks)} total tracks in playlist")

        # Create a dictionary to track seen tracks and their positions
        seen = {}
        duplicates = []
        for i, item in enumerate(tracks):
            track = item.get("track")
            if not track:
                continue
                
            key = (track["name"], track["artists"][0]["name"] if track["artists"] else None)
            if key in seen:
                # This is a duplicate, add it to the list to remove
                duplicates.append({
                    "uri": track["uri"],
                    "positions": [i]
                })
                logger.info(f"Found duplicate: {track['name']} by {track['artists'][0]['name']}")
            else:
                # First time seeing this track, keep it
                seen[key] = i
                logger.info(f"Keeping track: {track['name']} by {track['artists'][0]['name']}")

        if not duplicates:
            logger.info("No duplicates found in playlist")
            return jsonify({"message": "No duplicates found"})

        logger.info(f"Found {len(duplicates)} duplicates to remove")

        # Remove duplicates in batches of 100
        removed_count = 0
        for i in range(0, len(duplicates), 100):
            batch = duplicates[i:i + 100]
            payload = {"tracks": batch}
            response = requests.delete(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            removed_count += len(batch)
            logger.info(f"Removed batch of {len(batch)} duplicate tracks")

        # Verify the final state
        final_tracks = []
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            final_tracks.extend(data.get("items", []))
            url = data.get("next")

        logger.info(f"Final playlist state: {len(final_tracks)} tracks remaining")

        return jsonify({
            "status": "success",
            "removed_count": removed_count,
            "remaining_tracks": len(final_tracks),
            "message": f"Removed {removed_count} duplicate tracks while keeping one copy of each"
        })
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error in remove_duplicates: {str(e)}")
        return jsonify({"error": "Failed to communicate with Spotify API"}), 503
    except Exception as e:
        logger.error(f"Error in remove_duplicates: {str(e)}")
        return jsonify({"error": "Failed to remove duplicates"}), 500

@app.route("/shuffle-smart", methods=["POST"])
@require_auth
def shuffle_smart():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        playlist_id = data.get("playlist_id")
        
        if not playlist_id:
            return jsonify({"error": "Missing playlist_id"}), 400

        tokens = token_storage.get_tokens(user_id)
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        
        # Get playlist tracks
        tracks = []
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        
        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            tracks.extend([item["track"]["uri"] for item in data["items"] if item["track"]])
            url = data.get("next")

        # Get audio features for all tracks
        features = []
        for i in range(0, len(tracks), 100):
            batch = tracks[i:i + 100]
            response = requests.get(
                "https://api.spotify.com/v1/audio-features",
                headers=headers,
                params={"ids": ",".join(batch)}
            )
            response.raise_for_status()
            features.extend(response.json()["audio_features"])

        # Sort tracks by audio features
        sorted_tracks = [t for t, f in sorted(zip(tracks, features), 
                       key=lambda x: (x[1]["danceability"], x[1]["energy"], x[1]["valence"]))]

        # Update playlist
        response = requests.put(
            f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
            headers=headers,
            json={"uris": sorted_tracks}
        )
        response.raise_for_status()

        return jsonify({"message": "Playlist shuffled successfully"})
    except Exception as e:
        logger.error(f"Error in smart shuffle: {str(e)}")
        return jsonify({"error": "Failed to shuffle playlist"}), 500

@app.route("/generate-playlist", methods=["POST"])
def generate_playlist():
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        seed_uris = data.get("seeds", [])
        name = data.get("name", "Generated Playlist")

        logger.info(f"Generating playlist for user {user_id} with {len(seed_uris)} seeds")

        if not user_id or not seed_uris:
            logger.error("Missing user_id or seeds")
            return jsonify({"error": "Missing user_id or seeds"}), 400

        tokens = token_storage.get_tokens(user_id)
        if not tokens:
            logger.error(f"User {user_id} not authorized")
            return jsonify({"error": "User not authorized"}), 401

        headers = {
            "Authorization": f"Bearer {tokens['access_token']}",
            "Content-Type": "application/json"
        }

        # Get user profile
        try:
            me_response = requests.get("https://api.spotify.com/v1/me", headers=headers)
            me_response.raise_for_status()
            user_profile = me_response.json()
            logger.info(f"Got user profile for {user_profile['id']}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user profile: {str(e)}")
            return jsonify({"error": "Failed to get user profile"}), 503

        # Create new playlist
        try:
            create_payload = {
                "name": name,
                "description": "Generated by Spotik GPT",
                "public": False
            }
            create_response = requests.post(
                f"https://api.spotify.com/v1/users/{user_profile['id']}/playlists",
                headers=headers,
                json=create_payload
            )
            create_response.raise_for_status()
            new_playlist = create_response.json()
            logger.info(f"Created new playlist: {new_playlist['id']}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to create playlist: {str(e)}")
            return jsonify({"error": "Failed to create playlist"}), 503

        # Get recommendations
        try:
            seed_tracks = [s for s in seed_uris if "track" in s]
            seed_artists = [s for s in seed_uris if "artist" in s]
            seed_genres = [s for s in seed_uris if "genre" in s]

            rec_params = {
                "limit": 30,
                "seed_tracks": ",".join([s.split(":")[-1] for s in seed_tracks[:5]]),
                "seed_artists": ",".join([s.split(":")[-1] for s in seed_artists[:2]]),
                "seed_genres": ",".join([s.split(":")[-1] for s in seed_genres[:2]])
            }

            logger.info(f"Getting recommendations with params: {rec_params}")
            rec_response = requests.get(
                "https://api.spotify.com/v1/recommendations",
                headers=headers,
                params=rec_params
            )
            rec_response.raise_for_status()
            tracks = rec_response.json().get("tracks", [])
            
            if not tracks:
                logger.warning("No recommendations found")
                return jsonify({"error": "No recommendations found"}), 404

            logger.info(f"Got {len(tracks)} recommended tracks")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get recommendations: {str(e)}")
            return jsonify({"error": "Failed to get recommendations"}), 503

        # Add tracks to playlist in batches of 100
        try:
            track_uris = [t["uri"] for t in tracks]
            for i in range(0, len(track_uris), 100):
                batch = track_uris[i:i + 100]
                add_response = requests.post(
                    f"https://api.spotify.com/v1/playlists/{new_playlist['id']}/tracks",
                    headers=headers,
                    json={"uris": batch}
                )
                add_response.raise_for_status()
                logger.info(f"Added batch of {len(batch)} tracks to playlist")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to add tracks to playlist: {str(e)}")
            return jsonify({"error": "Failed to add tracks to playlist"}), 503

        return jsonify({
            "status": "success",
            "playlist_id": new_playlist['id'],
            "name": name,
            "tracks_added": len(track_uris),
            "playlist_url": new_playlist['external_urls']['spotify']
        })
    except Exception as e:
        logger.error(f"Unexpected error in generate_playlist: {str(e)}")
        return jsonify({"error": "Failed to generate playlist"}), 500

@app.route("/profile")
def musical_profile():
    user_id = request.args.get("user_id")
    if not user_id or user_id not in token_storage._tokens:
        return jsonify({"error": "User not authorized"}), 401

    access_token = token_storage._tokens[user_id]["access_token"]
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
    if not user1 or not user2 or user1 not in token_storage._tokens or user2 not in token_storage._tokens:
        return jsonify({"error": "Both users must be authorized"}), 400

    def get_top(user_id):
        access_token = token_storage._tokens[user_id]["access_token"]
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
    if not user_id or not seed_uri or user_id not in token_storage._tokens:
        return jsonify({"error": "Missing user_id or seed_uri, or user not authorized"}), 400

    access_token = token_storage._tokens[user_id]["access_token"]
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
    rec_url = f"https://api.spotify.com/v1/recommendations"
    if seed_type not in ["track", "artist", "genre"]:
        return jsonify({"error": "Unsupported seed type"}), 400

    recs = requests.get(rec_url, headers=headers, params=params).json()

    new_tracks = [t for t in recs.get("tracks", []) if t["uri"] not in all_uris]
    uris = [t["uri"] for t in new_tracks[:30]]

    return jsonify({
        "recommended": uris,
        "excluded_duplicates": len(recs.get("tracks", [])) - len(uris)
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
