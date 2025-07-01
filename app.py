import os
import random
import time
import threading
import gradio as gr
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import MemoryCacheHandler

# Environment variables for Spotify credentials and redirect
CLIENT_ID     = os.environ["SPOTIFY_CLIENT_ID"]
CLIENT_SECRET = os.environ["SPOTIFY_CLIENT_SECRET"]
REDIRECT_URI  = os.environ["REDIRECT_URI"]
SCOPE = "user-read-playback-state user-modify-playback-state playlist-read-private"

# Function to create a new OAuth manager per session
def create_oauth_manager():
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        show_dialog=True,
        cache_handler=MemoryCacheHandler()
    )

# Core functions don't use globals anymore, read from state

def get_auth_url(oauth_state):
    return oauth_state["manager"].get_authorize_url()

def try_login(current_url, oauth_state, playlist_state, device_state):
    # oauth_state: { "manager": SpotifyOAuth, "token_info": {} }
    manager = oauth_state.get("manager") or create_oauth_manager()
    oauth_state["manager"] = manager

    if "?code=" not in current_url:
        return (
            "🔐 Please login to Spotify.",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            oauth_state,
            {},
            {}
        )

    code = current_url.split("?code=")[1].split("&")[0]
    token_info = manager.get_cached_token()
    if not token_info:
        token_info = manager.get_access_token(code)
    oauth_state["token_info"] = token_info

    # Create Spotify client per call
    sp = spotipy.Spotify(auth=token_info["access_token"])

    # Fetch playlists & devices for this user
    try:
        items = sp.current_user_playlists(limit=50)["items"]
    except Exception as e:
        return (f"❌ Failed to get playlists: {e}",
                *([gr.update(visible=False)]*3),
                oauth_state,
                {},
                {})

    playlists = {p["name"]: p["id"] for p in items}
    devices  = {d["name"]: d["id"] for d in sp.devices()["devices"]}

    return (
        "✅ Logged in!",
        gr.update(visible=True, choices=list(playlists.keys())),
        gr.update(visible=True, choices=list(devices.keys())),
        gr.update(visible=True),
        oauth_state,
        playlists,
        devices
    )


def background_queue_tracks(uris, device_id, token_info):
    sp = spotipy.Spotify(auth=token_info["access_token"])
    for i, uri in enumerate(uris):
        try:
            sp.add_to_queue(uri, device_id=device_id)
            time.sleep(0.25)
        except Exception:
            time.sleep(1)


def shuffle_and_play_stream(playlist_name, device_name, oauth_state, playlist_state, device_state):
    pid = playlist_state.get(playlist_name)
    device_id = device_state.get(device_name)
    if not pid or not device_id:
        yield "❌ Invalid playlist or device."
        return

    token_info = oauth_state.get("token_info")
    sp = spotipy.Spotify(auth=token_info["access_token"])

    # Collect & shuffle URIs
    tracks, res = [], sp.playlist_tracks(pid)
    tracks.extend(res["items"])
    while res.get("next"):
        res = sp.next(res)
        tracks.extend(res["items"])
    uris = [t["track"]["uri"] for t in tracks if t.get("track")]
    random.shuffle(uris)

    # Start playback & queue
    try:
        sp.start_playback(device_id=device_id, uris=uris[:100])
        threading.Thread(target=background_queue_tracks,
                         args=(uris[100:200], device_id, token_info),
                         daemon=True).start()
    except Exception as e:
        yield f"❌ Playback failed: {e}"
        return

    yield "✅ Playlist shuffled!"
    time.sleep(10)
    yield now_playing(oauth_state)


def now_playing(oauth_state):
    token_info = oauth_state.get("token_info")
    sp = spotipy.Spotify(auth=token_info["access_token"])
    data = sp.current_playback()
    if not data or not data.get("is_playing"):
        return "⚠️ Nothing is currently playing."
    track = data["item"]
    name = track["name"]
    artist = ", ".join([a["name"] for a in track["artists"]])
    album = track["album"]["name"]
    image = track["album"]["images"][0]["url"]
    return f"<img src='{image}' width='300'><br><b>{name}</b> by {artist}<br/><i>{album}</i>"

with gr.Blocks() as demo:
    # Per-session state
    oauth_state     = gr.State({})
    playlist_state  = gr.State({})
    device_state    = gr.State({})

    gr.Markdown("## 🎵 Multi-User Spotify Shuffler")
    gr.HTML(lambda s: f'<a href="{get_auth_url(s)}">'
                    "<button style='width:100%;height:40px;'>🔐 Login to Spotify</button></a>",
             inputs=[oauth_state])

    url_state   = gr.Textbox(visible=False)
    status      = gr.Markdown()
    playlist_dd = gr.Dropdown(label="Select Playlist", visible=False)
    device_dd   = gr.Dropdown(label="Select Device", visible=False)
    shuffle_btn = gr.Button("🔀 Shuffle & Play", visible=False)
    result      = gr.HTML()

    demo.load(
        fn=try_login,
        inputs=[url_state, oauth_state, playlist_state, device_state],
        outputs=[status, playlist_dd, device_dd, shuffle_btn,
                 oauth_state, playlist_state, device_state],
        js="() => [window.location.href]"
    )

    shuffle_btn.click(
        shuffle_and_play_stream,
        inputs=[playlist_dd, device_dd,
                oauth_state, playlist_state, device_state],
        outputs=[result]
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    demo.launch(server_name="0.0.0.0", server_port=port, share=False)

