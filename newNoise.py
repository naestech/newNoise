import spotipy
from spotipy.oauth2 import SpotifyOAuth
import time
from datetime import datetime, timedelta
import json
from config import *
from database import ArtistDatabase

class SpotifyNewReleasesTracker:
    def __init__(self):
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope=SCOPE
        ))
        self.playlist_id = self._get_or_create_playlist()
        self.archive_playlist_id = self._get_or_create_archive_playlist()
        self.db = ArtistDatabase()

    def _get_or_create_playlist(self):
        """Get existing playlist or create a new one"""
        playlists = self.sp.current_user_playlists()
        for playlist in playlists['items']:
            if playlist['name'] == PLAYLIST_NAME:
                return playlist['id']
        
        user_id = self.sp.current_user()['id']
        playlist = self.sp.user_playlist_create(
            user_id, 
            PLAYLIST_NAME, 
            description="Automatically updated with latest releases from followed artists"
        )
        return playlist['id']

    def _get_or_create_archive_playlist(self):
        """Get existing archive playlist or create a new one"""
        playlists = self.sp.current_user_playlists()
        for playlist in playlists['items']:
            if playlist['name'] == ARCHIVE_PLAYLIST_NAME:
                return playlist['id']
        
        user_id = self.sp.current_user()['id']
        playlist = self.sp.user_playlist_create(
            user_id, 
            ARCHIVE_PLAYLIST_NAME, 
            description="Archive of songs removed from new noise playlist"
        )
        return playlist['id']

    def add_artist(self, artist_name):
        """Add a new artist to track"""
        results = self.sp.search(q=artist_name, type='artist')
        if results['artists']['items']:
            artist = results['artists']['items'][0]
            artist_id = artist['id']
            artist_url = artist['external_urls']['spotify']
            
            if self.db.add_artist(artist_id, artist_name, artist_url):
                print(f"Adding {artist_name} to track...")
                return True
            else:
                print(f"Artist {artist_name} already exists in database")
                return False
        return False

    def get_recent_tracks(self):
        """Get recent tracks from all tracked artists"""
        recent_tracks = []
        artist_ids = self.db.get_artist_ids()
        
        for artist_id in artist_ids:
            albums = self.sp.artist_albums(
                artist_id, 
                album_type='album,single',
                limit=5
            )
            
            for album in albums['items']:
                tracks = self.sp.album_tracks(album['id'])
                for track in tracks['items'][:TRACKS_PER_ARTIST]:
                    # Only include tracks where the artist is primary artist
                    if artist_id == track['artists'][0]['id']:
                        recent_tracks.append(track['id'])
                        
        return recent_tracks[:50]  # Spotify playlist update has a 50 track limit

    def update_playlist(self):
        """Update both New Noise and New Noise Archive playlists with recent releases"""
        # Get current tracks in both playlists to avoid duplicates
        current_tracks = self.sp.playlist_tracks(self.playlist_id, fields='items(track(id))')
        archive_tracks = self.sp.playlist_tracks(self.archive_playlist_id, fields='items(track(id))')
        
        current_track_ids = {track['track']['id'] for track in current_tracks['items']}
        archive_track_ids = {track['track']['id'] for track in archive_tracks['items']}
        
        # Get all artist IDs
        artist_ids = self.db.get_artist_ids()
        
        # Track new additions
        new_tracks = []
        archive_tracks = []
        
        # Process each artist's recent releases
        for artist_id in artist_ids:
            albums = self.sp.artist_albums(
                artist_id,
                album_type='album,single',
                limit=5  # Limit to most recent releases
            )
            
            for album in albums['items']:
                release_date = album['release_date']
                
                # Skip if album is older than ARCHIVE_DAYS
                if not self._is_within_month(release_date):
                    continue
                    
                tracks = self.sp.album_tracks(album['id'])
                for track in tracks['items']:
                    # Only include tracks where the artist is primary artist
                    if track['artists'][0]['id'] != artist_id:
                        continue
                    
                    track_id = track['id']
                    # Skip if track is already in either playlist
                    if track_id in current_track_ids or track_id in archive_track_ids:
                        continue
                    
                    # Add to appropriate playlist based on release date
                    if self.is_track_from_current_week(release_date):
                        new_tracks.append(track_id)
                    elif self._is_within_archive_period(release_date):
                        archive_tracks.append(track_id)
        
        # Update playlists (in batches of 50 due to Spotify API limits)
        new_tracks_added = 0
        archive_tracks_added = 0
        
        # Add new tracks to main playlist
        for i in range(0, len(new_tracks), 50):
            batch = new_tracks[i:i + 50]
            self.sp.playlist_add_items(self.playlist_id, batch)
            new_tracks_added += len(batch)
        
        # Add tracks to archive playlist
        for i in range(0, len(archive_tracks), 50):
            batch = archive_tracks[i:i + 50]
            self.sp.playlist_add_items(self.archive_playlist_id, batch)
            archive_tracks_added += len(batch)
        
        print(f"Updated New Noise playlist: {new_tracks_added} new songs added")
        print(f"Updated New Noise Archive playlist: {archive_tracks_added} new songs added")

    def is_track_from_current_week(self, release_date):
        """Check if the track's release date is from the current week"""
        try:
            today = datetime.now()
            if len(release_date) == 4:  # Year only
                return False
            elif len(release_date) == 7:  # Year-month format
                track_date = datetime.strptime(release_date + '-01', '%Y-%m-%d')
            else:  # Full date format
                track_date = datetime.strptime(release_date, '%Y-%m-%d')
            
            # If the track date is in the future, consider it as today
            if track_date > today:
                track_date = today
            
            start_of_week = today - timedelta(days=today.weekday())
            end_of_week = start_of_week + timedelta(days=6)
            
            return start_of_week <= track_date <= end_of_week
        except ValueError:
            print(f"Warning: Invalid release date format: {release_date}")
            return False
        
    def get_new_releases(self, artist_ids):
        """Get new releases from the past week more efficiently"""
        new_tracks = []
        # Batch artists in groups of 20 (Spotify's limit for artist albums endpoint)
        for i in range(0, len(artist_ids), 20):
            batch_ids = artist_ids[i:i + 20]
            
            # Process each artist individually since there's no batch endpoint
            for artist_id in batch_ids:
                albums = self.sp.artist_albums(
                    artist_id,
                    album_type='album,single',
                    limit=5
                )
                
                if not albums:
                    continue
                    
                # Filter albums by date first
                recent_albums = [
                    album for album in albums['items']
                    if self.is_track_from_current_week(album['release_date'])
                ]
                
                if not recent_albums:
                    continue
                
                # Batch album track requests (max 20 per request)
                album_ids = [album['id'] for album in recent_albums]
                for j in range(0, len(album_ids), 20):
                    batch_album_ids = album_ids[j:j + 20]
                    for album_id in batch_album_ids:
                        album_tracks = self.sp.album_tracks(album_id)
                        for track in album_tracks['items'][:TRACKS_PER_ARTIST]:
                            # Only include tracks where the artist is primary artist
                            if track['artists'][0]['id'] in artist_ids:
                                new_tracks.append(track['id'])
        
        return list(set(new_tracks[:50]))

    def _is_within_month(self, release_date):
        """Check if the release date is within the past month"""
        try:
            today = datetime.now()
            if len(release_date) == 4:  # Year only
                return False
            elif len(release_date) == 7:  # Year-month format
                track_date = datetime.strptime(release_date + '-01', '%Y-%m-%d')
            else:  # Full date format
                track_date = datetime.strptime(release_date, '%Y-%m-%d')
            
            if track_date > today:
                track_date = today
            
            cutoff = today - timedelta(days=ARCHIVE_DAYS)
            return track_date >= cutoff
        except ValueError:
            return False

    def _is_within_archive_period(self, release_date):
        """Check if the release date is between 1 week and 1 month old"""
        try:
            today = datetime.now()
            if len(release_date) == 4:  # Year only
                return False
            elif len(release_date) == 7:  # Year-month format
                track_date = datetime.strptime(release_date + '-01', '%Y-%m-%d')
            else:  # Full date format
                track_date = datetime.strptime(release_date, '%Y-%m-%d')
            
            if track_date > today:
                track_date = today
            
            week_ago = today - timedelta(days=7)
            month_ago = today - timedelta(days=ARCHIVE_DAYS)
            
            return month_ago <= track_date <= week_ago
        except ValueError:
            return False

    def _clean_archive_playlist_batch(self):
        """Remove old tracks from archive playlist more efficiently"""
        archive_tracks = self.sp.playlist_tracks(self.archive_playlist_id, fields='items(track(id,album(id)))')
        
        # Get unique album IDs
        album_ids = {track['track']['album']['id'] for track in archive_tracks['items']}
        
        # Batch album requests
        albums_data = {}
        for i in range(0, len(album_ids), 20):
            batch_ids = list(album_ids)[i:i + 20]
            batch_albums = self.sp.albums(batch_ids)
            for album in batch_albums:
                albums_data[album['id']] = album['release_date']
        
        # Find tracks to remove
        tracks_to_remove = []
        for track in archive_tracks['items']:
            track_id = track['track']['id']
            album_id = track['track']['album']['id']
            release_date = albums_data.get(album_id)
            
            if release_date and not self._is_within_archive_period(release_date):
                tracks_to_remove.append(track_id)
        
        # Remove tracks in batches
        if tracks_to_remove:
            for i in range(0, len(tracks_to_remove), 100):
                chunk = tracks_to_remove[i:i + 100]
                self.sp.playlist_remove_all_occurrences_of_items(
                    self.archive_playlist_id, 
                    chunk
                )
            print(f"Removed {len(tracks_to_remove)} old tracks from archive")

def main():
    tracker = SpotifyNewReleasesTracker()
    
    while True:
        print("\n1. Update playlist")
        print("2. Add artist(s)")
        print("3. List artist(s)")
        print("4. Remove artist(s)")
        print("5. Exit")
        choice = input("Choose an option: ")
        
        if choice == '1':
            tracker.update_playlist()
        elif choice == '2':
            print("Enter artist name(s) - separate multiple artists with commas")
            artist_input = input("Artist(s): ")
            artist_names = [name.strip() for name in artist_input.split(',')]
            
            for artist_name in artist_names:
                if artist_name:  # Skip empty names
                    if tracker.add_artist(artist_name):
                        print(f"Added {artist_name}")
                    else:
                        print(f"Failed to add {artist_name}")
        elif choice == '3':
            artists = tracker.db.get_all_artists()
            print("\nTracked Artists:")
            for id, name, url in artists:
                print(f"- {name} ({url})")
        elif choice == '4':
            print("Enter artist name(s) to remove - separate multiple artists with commas")
            artist_input = input("Artist(s) to remove: ")
            artist_names = [name.strip() for name in artist_input.split(',')]
            
            artists = tracker.db.get_all_artists()
            for artist_name in artist_names:
                if not artist_name:  # Skip empty names
                    continue
                    
                found = False
                for artist_id, name, _ in artists:
                    if name.lower() == artist_name.lower():
                        if tracker.db.remove_artist(artist_id):
                            print(f"Removed {name}")
                        else:
                            print(f"Failed to remove {name}")
                        found = True
                        break
                
                if not found:
                    print(f"Artist '{artist_name}' not found")
        elif choice == '5':
            break
        else:
            print("Invalid choice")

if __name__ == "__main__":
    main() 