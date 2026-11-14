---
modified: 2026-11-14T15:58:39+00:00
---
# ChatGPT voice chat on a Nokia N95 8GB

Give a 2007 Nokia N95 8GB text chat and two-way, push-to-talk conversations
with OpenAI models. The phone runs a small Java ME application. A Python
bridge on your Linux computer handles modern HTTPS, speech transcription,
and speech generation.

Tested on a real Nokia N95 8GB with an Omarchy Linux bridge. Text chat,
recording, transcription, spoken replies, and the handset's multimedia
permission setting have been confirmed working by the owner.

<img src="assets/icon-source-v2.png" alt="N95 ChatGPT application icon" width="128" height="128">

## What you need

- A Nokia N95 8GB with working Wi-Fi and Java application support.
- A **mini-USB data cable** to copy the application to the phone. This is the
  older mini-USB connector, not micro-USB or USB-C. The cable must support data.
- A Linux computer on the same reachable network as the phone.
- An OpenAI API key with access and billing for the models you choose.
- Python 3, FFmpeg, Git, curl, and tar. Python uses only its standard library.
- JDK 8 and the Java ME build dependencies installed by the setup script.

The phone uses Wi-Fi for conversations. USB is for installation.
The bridge must remain running while you use the app.

## 1. Get the source and build the phone app

Clone the repository:

```bash
git clone https://github.com/conoro/nokia-n95-chatgpt.git
cd nokia-n95-chatgpt
```

Install the host dependencies with your distribution's package manager.
For Omarchy / Arch Linux:

```bash
sudo pacman -S --needed python ffmpeg git curl tar
```

For Debian / Ubuntu:

```bash
sudo apt install python3 ffmpeg git curl tar
```

Download the local build tools and compile:

```bash
./scripts/setup-toolchain.sh
./build.sh
```

On Linux x86-64 the setup script downloads Temurin JDK 8u512-b09 locally.
It also downloads ProGuard 6.2.2 and a pinned Java ME API-library template.
JDK and ProGuard downloads are checked against SHA-256 hashes. Nothing is
installed system-wide by this script. On other architectures, install a JDK 8
for your platform and set `JAVA_HOME` before building.

The outputs are `dist/N95ChatGPT.jar` and `dist/N95ChatGPT.jad`.
The JAR is preverified for CLDC 1.0 / MIDP 2.0 and uses JSR-135 for audio.
Build outputs and downloaded dependencies are excluded from Git.

## 2. Configure and start the bridge

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` with your editor. Set:

- `OPENAI_API_KEY` to your API key.
- `OPENAI_MODEL` to a Responses API model available to your project.
- `BRIDGE_TOKEN` to a token you choose. You will also enter this on the phone.

The remaining settings choose the listening address, port, transcription model,
and speech model and voice. The defaults use port 8095 and the alloy voice.
Model availability can change. Update these values if your account reports
an unavailable model.

Start the bridge from the project directory:

```bash
python3 proxy/server.py
```

The server automatically loads the project's `.env`, even if launched from a
different directory. Exported environment variables take precedence. Restart
the bridge whenever its code or configuration changes.

Find your computer's LAN IPv4 address in your network settings. For example,
if it is `192.168.1.100`, the phone's bridge URL is
`http://192.168.1.100:8095`. Include the port. The app's initial address is a
placeholder that you must replace.

Check the bridge locally by opening `http://localhost:8095/health`. It should
say `N95 bridge ready`. Your firewall must allow the phone to reach TCP 8095.
Guest Wi-Fi or client isolation can prevent the two devices communicating.

## 3. Install on the phone

1. Connect the mini-USB data cable and choose **Data transfer** on the N95.
2. Copy both files from `dist/` to the phone's mass storage.
3. Safely eject the storage, then disconnect USB.
4. On the phone, use File manager to open `N95ChatGPT.jar` and install it.
5. If unsigned applications are blocked, check Application manager's
   installation settings. This is an unsigned Java application.
6. Open **N95 ChatGPT → Settings**. Enter the bridge URL and your bridge token,
   then Save. Allow network access and choose your Wi-Fi access point.

On upgrades, saved settings take precedence over the app's compiled defaults.

### Reduce microphone permission prompts

Close the app. In **Tools → App. mgr.**, highlight **N95 ChatGPT**, then choose
**Options → Suite settings → Multimedia** (wording can vary). Choose
**Always allowed** or **Ask first time** if offered. Changing this setting
resolved repeated recording prompts on the tested N95 8GB. Available choices
can depend on firmware and application trust.

## 4. Talk or type

**Text:** enter a message and choose Send.

**Voice:** choose Voice, hold the centre navigation button or 5, speak when
Recording appears, then release. Alternatively, use Record / Stop to start
and finish. The app automatically transcribes your words, sends them to the
chat model, displays the answer, and plays an AI-generated spoken reply.

If a permission dialog consumes the key release, choose Record / Stop to
finish. Back cancels recording. Stop speech stops playback. Starting a new
voice turn stops the previous spoken reply.

Text and voice use the same conversation. New conversation clears the local
transcript and continuation ID. Settings persist after exit. Conversations
are held in memory and reset when the application exits.

## How it works

```text
N95 microphone → HTTP audio upload → Python bridge → OpenAI transcription
N95 transcript → HTTP text request → Python bridge → OpenAI Responses
N95 speaker   ← HTTP MP3 download  ← Python bridge ← OpenAI speech generation
```

The bridge converts handset audio, including AMR, into mono 16 kHz WAV using
FFmpeg. The client automatically chains transcription, chat, and speech
requests. Responses API IDs maintain conversation context. The phone downloads
the complete MP3 before playback. This is turn-based voice. A continuous Realtime session with interruption
detection would require further work.

## Privacy and limits

- Phone-to-bridge traffic is plain HTTP, including messages, audio, and the
  bridge token. Use a trusted LAN. The default bind address in `.env.example`
  exposes the service to reachable network devices. Do not port-forward it.
- The OpenAI API key stays on the bridge. The bridge uses HTTPS upstream.
  Recordings, transcriptions, and reply text are sent to OpenAI as needed.
- Responses use `store: true` for continuation. New conversation does not
  delete previously stored responses from OpenAI.
- `.env` is Git-ignored. Never commit keys or your local configuration.
- Recordings stop at 30 seconds and are capped at 2 MiB. Speech input is limited
  to 4096 characters and downloaded speech to 2 MiB. Text answers remain
  visible if speech fails. Visible history is capped at 12,000 characters.
- API stages are separate billable requests. Retrying a failed connection may
  produce another billable request if the earlier call already completed.
- Pending network requests can take time to finish after Stop speech.

## Troubleshooting

- **Connection failed / IOException -36:** check the bridge is running, restart
  it after updates, and verify the saved URL, port, Wi-Fi and firewall. The
  error alone does not identify the cause.
- **HTTP 401:** the phone token and `BRIDGE_TOKEN` must match.
- **HTTP 404 after upgrading:** restart the bridge to load new endpoints.
- **OpenAI HTTP error:** check the configured model, API key, quota and billing.
- **Could not decode recording:** check FFmpeg is installed and try a short clip.
- **Recording prompt interrupts PTT:** approve it, then use Record / Stop, or
  adjust the multimedia permission setting above.
- **Build cannot find Java:** use JDK 8 and set `JAVA_HOME` to its installation
  directory, or run the setup script on Linux x86-64.

## macOS (not tested)

The Python bridge and shell build scripts should also work on macOS. Install
Python 3, FFmpeg, Git and a macOS JDK 8 matching your CPU. Set `JAVA_HOME` to
that JDK's Home directory, then run the setup and build scripts above. The
setup script downloads the API libraries and ProGuard but relies on your JDK
on macOS. If installed and registered with macOS, JDK 8 can be selected with:

```bash
export JAVA_HOME="$(/usr/libexec/java_home -v 1.8)"
```

Use the same `.env` setup. USB Data transfer should expose the phone as mass
storage in Finder. Neither macOS builds nor transfers have been tested here.

## Development and acknowledgements

```bash
python3 -m unittest discover -s proxy -v
./build.sh
```

The integration tests use real local HTTP and FFmpeg conversion with simulated
OpenAI replies. Real handset testing confirmed the voice workflow. An actual
OpenAI TTS call was also checked for valid MP3 output.

Build API libraries come from
[gtrxAC/j2me-template](https://github.com/gtrxAC/j2me-template), pinned to
`b1be318cef88a0d2a1239841b9c45190a4df2401`. Its library notes identify WTK,
Nokia SDK and KEmulator sources. Those external binaries retain their own
licensing terms and are downloaded separately. The template's MIT licence
does not establish a blanket licence for every SDK binary.

The icon was generated with OpenAI image generation and resized to 48×48.
The application is an independent project, unaffiliated with Nokia or OpenAI.
The project's own source is released under the MIT licence.
