from newNoise import SpotifyNewReleasesTracker
import schedule
import time

def update_job():
    tracker = SpotifyNewReleasesTracker()
    tracker.update_playlist()
    print(f"Playlist updated at {time.strftime('%Y-%m-%d %H:%M:%S')}")

# Schedule the job to run once per day
schedule.every().day.at("00:00").do(update_job)

while True:
    schedule.run_pending()
    time.sleep(60)