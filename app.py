import os
import random
import time
import threading
import gradio as gr
import spotipy
from spotipy.oauth2 import SpotifyOAuth

CLIENT_ID = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI  = os.environ["REDIRECT_URI"]
SCOPE = "user-read-playback-state user-modify-playback-state playlist-read-private"

sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE,
    show_dialog=True,
)

sp = None
user_playlists = {}
device_map = {}

def get_auth_url():
    return sp_oauth.get_authorize_url()

def try_login(current_url):
    global sp, user_playlists, device_map

    if "?code=" not in current_url:
        return (
            "🔐 Please login to Spotify.",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    code = current_url.split("?code=")[1].split("&")[0]
    try:
        token_info = sp_oauth.get_cached_token()
        if not token_info:
            token_info = sp_oauth.get_access_token(code)
        access_token = token_info["access_token"]
    except Exception as e:
        print("🔁 Token refresh failed:", str(e))
        return (
            f"❌ Failed to log in: {e}",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    sp = spotipy.Spotify(auth=access_token)

    try:
        playlists = sp.current_user_playlists(limit=50)["items"]
    except Exception as e:
        return f"❌ Failed to get playlists: {e}", *[gr.update(visible=False)] * 3

    user_playlists.clear()
    for p in playlists:
        user_playlists[p["name"]] = p["id"]

    devices = sp.devices()["devices"]
    device_map.clear()
    for d in devices:
        device_map[d["name"]] = d["id"]

    if not device_map:
        return (
            "⚠️ No active Spotify devices found.",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    return (
        "✅ Logged in!",
        gr.update(visible=True, choices=list(user_playlists.keys())),
        gr.update(visible=True, choices=list(device_map.keys())),
        gr.update(visible=True),
    )

def background_queue_tracks(uris, device_id):
    for i, uri in enumerate(uris):
        try:
            sp.add_to_queue(uri, device_id=device_id)
            time.sleep(0.25)
        except Exception as e:
            print(f"[Queue Error] Track {i}: {e}")
            time.sleep(1)

def now_playing():
    try:
        data = sp.current_playback()
        if not data or not data.get("is_playing"):
            return "⚠️ Nothing is currently playing."
        track = data["item"]
        name = track["name"]
        artist = ", ".join([a["name"] for a in track["artists"]])
        album = track["album"]["name"]
        image = track["album"]["images"][0]["url"]
        html = f"""
        <img src='{image}' width='300'><br>
        <b>{name}</b> by {artist}<br/>
        <i>{album}</i>
        """
        return html
    except Exception as e:
        return f"❌ Error fetching current track: {e}"

def delayed_now_playing(output):
    time.sleep(10)
    output.update(now_playing())

def shuffle_and_play(playlist_name, device_name):
    pid = user_playlists.get(playlist_name)
    device_id = device_map.get(device_name)

    if not pid or not device_id:
        return "❌ Invalid playlist or device."

    tracks, res = [], sp.playlist_tracks(pid)
    tracks.extend(res["items"])
    while res["next"]:
        res = sp.next(res)
        tracks.extend(res["items"])

    uris = [t["track"]["uri"] for t in tracks if t["track"]]
    random.shuffle(uris)

    try:
        sp.start_playback(device_id=device_id, uris=uris[:100])
        threading.Thread(target=background_queue_tracks, args=(uris[100:200], device_id)).start()
        return "✅ Shuffling... Song info will display in ~10 seconds."
    except Exception as e:
        return f"❌ Playback failed: {str(e)}"

with gr.Blocks() as demo:
    gr.Markdown("## 🎵 RNG Spotify Playlist Shuffler")
    gr.HTML(f'<a href="{get_auth_url()}"><button style="width:100%;height:40px;">🔐 Login to Spotify</button></a>')

    url_state = gr.Textbox(visible=False)
    status = gr.Markdown()
    playlist_dd = gr.Dropdown(label="Step 2: Select a Playlist", visible=False)
    device_dd = gr.Dropdown(label="Step 3: Select a Device", visible=False)
    shuffle_btn = gr.Button("🔀 Step 4: Shuffle & Play", visible=False)
    result = gr.HTML()

    demo.load(
        fn=try_login,
        inputs=[url_state],
        outputs=[status, playlist_dd, device_dd, shuffle_btn],
        js="() => { return [window.location.href]; }"
    )

    def handle_shuffle(playlist_name, device_name):
        result_text = shuffle_and_play(playlist_name, device_name)
        threading.Thread(target=delayed_now_playing, args=(result,)).start()
        return result_text

    shuffle_btn.click(handle_shuffle, [playlist_dd, device_dd], [result])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        share=False
    )

