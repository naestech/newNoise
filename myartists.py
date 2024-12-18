import spotipy
from spotipy.oauth2 import SpotifyOAuth
from config import SPOTIFY_CLIENT_ID as CLIENT_ID, SPOTIFY_CLIENT_SECRET as CLIENT_SECRET, SPOTIFY_REDIRECT_URI as REDIRECT_URI

def get_followed_artists():
    try:
        # Initialize Spotify client with necessary permissions
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope="user-follow-read"
        ))

        # Get all followed artists
        artists = []
        results = sp.current_user_followed_artists(limit=50)
        
        while results:
            for item in results['artists']['items']:
                artists.append(item['name'])
            
            # Check if there are more artists to fetch
            if results['artists']['next']:
                results = sp.next(results['artists'])
            else:
                results = None

        # Join artists with commas and print
        formatted_artists = ', '.join(artists)
        print(formatted_artists)

        # Optionally save to file
        with open('followed_artists.txt', 'w', encoding='utf-8') as file:
            file.write(formatted_artists)

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    get_followed_artists()