# CubeVision

Look at a Rubik's cube through Meta Ray-Ban glasses and get CFOP coaching in your ear, one step at a time.

```
 Ray-Ban Meta glasses            Android (thin relay)                   Web app (does all the work)
 ┌──────────────┐   DAT SDK    ┌──────────────────────┐   WebSocket   ┌───────────────────────────────────┐
 │ camera 15fps ├────────────►│ JPEG @ ~5 fps ────────┼──────────────►│ vision plug-in (friend's model)    │
 │ mic          ├─ Bluetooth ─►│ PCM16 (optional) ─────┼──────────────►│ speech plug-in (speech-to-speech)  │
 │ speakers     │◄─ Bluetooth ─┤ play audio / TTS ◄────┼───────────────┤ scan → validate → CFOP → track     │
 └──────────────┘              └──────────────────────┘   JSON events └───────────────────────────────────┘
```

## Layout

| Path | What it is |
|---|---|
| `backend/cubevision/cube.py` | Cube model. Move tables come from 3D geometry, not memorised tables. Handles wide, slice and rotation notation. |
| `backend/cubevision/pieces.py` | State validation: colour counts, impossible pieces, twisted corners, flipped edges, parity. Each error lists the stickers involved. |
| `backend/cubevision/assemble.py` | Builds a full cube from per-face observations. Works out each face's rotation and averages sticker colours across frames. |
| `backend/cubevision/solver/` | CFOP: optimal cross, F2L search (picks the easiest pair next), all 57 OLL and 21 PLL, and a 2-look beginner mode. |
| `backend/cubevision/tracker.py` | Live session: scanning → solving → solved. Follows the user's turns from what the camera sees. If the user makes a wrong move, it re-plans. |
| `backend/cubevision/plugins.py` | **Plug-in points for the vision model and speech-to-speech.** |
| `backend/cubevision/server.py` | FastAPI app: device WebSocket, REST test API, simulator, dashboard at `/`. |
| `mobile/` | Expo (React Native) relay app for Android and iPhone. The Meta Wearables Device Access Toolkit 1.0.1 is wrapped in a local Expo module, `mobile/modules/cube-glasses`: Kotlin for Android, Swift for iOS. |

## Run the web app

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q                      # 152 tests
.venv/bin/uvicorn cubevision.server:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Click **Scramble & scan**, then **Do all moves**. This runs the whole loop with a simulated cube, so you don't need glasses or a vision model.

From the command line:

```bash
.venv/bin/python scripts/feed.py scramble "R U R' F2 D L'"            # scan a virtual cube
.venv/bin/python scripts/feed.py file scripts/example_observations.json  # pipe in your own squares
.venv/bin/python scripts/feed.py solve                                  # follow the coach to solved
```

## Vision model contract (for the vision side)

Write a class with a `detect(jpeg: bytes) -> list[dict]` method. It returns one dict for each cube face visible in the frame. Run the server with `CUBEVISION_VISION=yourpkg.module:YourClass`.

```json
[{"grid": [["W","R","G"], ["O","W","W"], ["Y","B","W"]],
  "up": "G",
  "confidence": [[0.9, 0.8, 0.95], [1, 1, 1], [0.7, 1, 1]]}]
```

- `grid` gives the 3×3 colours **as they appear in the image**: row 0 is the top of the image. Use `W Y R O G B`, or `?` / `null` for a sticker you can't read. The centre colour identifies the face.
- The model **does not have to know the face's rotation.** The assembler tries every rotation and keeps the ones where every corner and edge is a real piece. On random scrambles this finds the right cube 99% of the time. Otherwise it reports "ambiguous" and asks to see two faces at once. It never silently picks a wrong cube.
- `up` is optional. It's the centre colour of the neighbouring face that appears above this face in the image, when both are visible. When given, it settles the rotation.
- `confidence` is optional. It weights the vote across frames, so a misread sticker in one frame gets outvoted.
- A sticker-list form also works: `{"center":"W","stickers":[{"row":0,"col":0,"color":"W","conf":0.9}, …]}`.
- The default colour scheme is Western: white opposite yellow, green opposite blue, red opposite orange. To change it, edit `DEFAULT_SCHEME` in `solver/cfop.py`.

## Speech-to-speech contract (for the speech side)

Run the server with `CUBEVISION_SPEECH=pkg.module:Class`. Every method is optional:

- `async speak(session_id, text) -> bytes | None`: turns each coaching line into audio, which the phone plays on the glasses. Return `None` and the phone uses its built-in TTS instead.
- `async on_audio(session_id, pcm16) -> list[events]`: receives mic audio from the glasses (16 kHz mono). Return events to send back, for example `{"type": "answer", "say": "..."}`.
- `context(session_id, snapshot)`: gets the current cube state, step and move after every update, so the agent can answer questions like "why that move?".

## Device protocol (`/ws/device?session=default`)

- **Phone → server, binary:** `0x01` + JPEG for a camera frame, `0x02` + PCM16 for mic audio.
- **Phone → server, JSON:** `hello`, `reset`, `config {level: full|2look, cross_color}`, `observations {faces}`, `load_state {state}`.
- **Server → phone:** JSON events `welcome`, `scan_progress`, `scan_error`, `solution`, `step`, `progress`, `step_done`, `off_track`, `lost`, `solved`. Any event with `say` gets spoken. If it also has `audio_b64`, the phone plays that audio instead of using TTS.

## Phone relay app (Expo, Android + iPhone)

The phone does no cube logic. A local Kotlin Expo module, `mobile/modules/cube-glasses`, handles:
- Talking to the glasses through Meta's SDK.
- JPEG-encoding the camera frames and sending them to the web app over one WebSocket.
- Playing the web app's replies on the glasses: `audio_b64` audio if sent, otherwise on-device text-to-speech of `say`.
- Optionally sending the glasses mic up to the server.

React Native only draws the screen.

**Install:** copy `dist/CubeVision.apk` to an Android 12+ phone and open it. You'll need to allow installs from unknown sources.

**First run:**
1. In the Meta AI app, open your glasses' settings and turn on **Developer Mode**. The APK uses app ID `0`, which only works in Developer Mode.
2. Start the web app on your computer: `uvicorn cubevision.server:app --host 0.0.0.0 --port 8000`. The phone and computer need to be on the same Wi-Fi.
3. In CubeVision, allow Bluetooth.
4. Set the server URL to `ws://<computer-LAN-IP>:8000/ws/device?session=default` and tap **Connect**.
5. Tap **Link glasses**. The Meta AI app opens; approve, and it returns to CubeVision.
6. Tap **Start camera**. The first time, Meta AI asks for camera permission.

**Mock glasses:** with no glasses connected, the phone's back camera can stand in for the glasses camera, using Meta's Mock Device Kit.

**Rebuild the APK:**
```bash
cd mobile && npm install
npx expo prebuild --platform android
cd android && ANDROID_HOME=<android-sdk> ./gradlew assembleRelease
# -> android/app/build/outputs/apk/release/app-release.apk
```
This needs JDK 17–24 and about 8 GB of free disk; the first build downloads the NDK. The release build is signed with the debug key, which is fine for sideloading. Set up a real keystore before distributing it.

**iPhone (via EAS cloud build):**

You need a free Expo account, logged in with `npx eas-cli@latest login`, and an Apple Developer account ($99/year). The iPhone needs iOS 17.2 or later.

```bash
cd mobile
npx eas-cli@latest device:create                          # register your iPhone (open the link on the phone)
npx eas-cli@latest build -p ios --profile preview         # sign in with your Apple ID when asked
```

When the build finishes, EAS shows a QR code and link. Open it on the iPhone to install the app. Then on the iPhone, turn on Settings → Privacy & Security → **Developer Mode** and restart when asked. Meta's iOS SDK frameworks are downloaded on `npm install` by `modules/cube-glasses/scripts/fetch-ios-sdk.js`, so EAS fetches them automatically.

To use your own Meta app ID for release channels instead of Developer Mode, change the two `meta-data` values in `mobile/modules/cube-glasses/android/src/main/AndroidManifest.xml` (Android) and `ios.infoPlist.MWDAT` in `mobile/app.json` (iOS).

Note: the DAT SDK is in developer preview. Store publishing isn't supported yet; to share the app beyond Developer Mode, use Meta's release channels.
