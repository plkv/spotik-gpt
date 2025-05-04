# Spotik GPT

A powerful Spotify integration API that provides enhanced playlist management and music recommendations.

## Features

- Smart playlist management
- Duplicate track detection and removal
- Smart playlist shuffling based on audio features
- Music recommendations
- User profile analysis
- User compatibility comparison
- Top tracks and playlists

## API Endpoints

- `/playlists` - Get all user playlists
- `/top-playlists` - Get top playlists by followers
- `/saved-playlists` - Get saved playlists from other users
- `/top-tracks` - Get user's top tracks
- `/duplicates` - Find duplicate tracks in a playlist
- `/remove-duplicates` - Remove duplicate tracks from a playlist
- `/shuffle-smart` - Smart shuffle playlist based on audio features
- `/generate-playlist` - Create a new playlist based on seed tracks
- `/profile` - Get user's musical profile
- `/compare-users` - Compare musical preferences between two users
- `/recommend-new` - Get music recommendations based on a track/album

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables:
   - `SPOTIFY_CLIENT_ID`
   - `SPOTIFY_CLIENT_SECRET`
   - `REDIRECT_URI`
   - `SECRET_KEY`

## Development

Run the development server:
```bash
python app.py
```

## Deployment

The application is configured for deployment on Render.com. The `render.yaml` file contains the necessary configuration.

## License

MIT 