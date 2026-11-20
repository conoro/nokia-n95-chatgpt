"""Persistent Realtime audio sessions with incremental PCM-to-MP3 encoding."""
import base64
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

_sessions = {}
_lock = threading.Lock()


class RealtimeError(Exception):
    pass


def receive(ws, deadline):
    ws.settimeout(max(0.1, deadline - time.monotonic()))
    event = json.loads(ws.recv())
    if event.get('type') == 'error':
        error = event.get('error', {})
        raise RealtimeError('Realtime error: ' + str(error.get('code', 'unknown')))
    return event


def acquire(session_id):
    import websocket
    with _lock:
        now = time.monotonic()
        for key, session in list(_sessions.items()):
            if not session['busy'] and now - session['used'] > 300:
                session['ws'].close()
                del _sessions[key]
        if session_id:
            session = _sessions.get(session_id)
            if session is None:
                raise RealtimeError('Realtime session expired. Choose New conversation.')
            if session['busy']:
                raise RealtimeError('Realtime session is busy')
            session['busy'] = True
            return session_id, session
        if len(_sessions) >= 8:
            raise RealtimeError('Realtime session limit reached; retry after idle expiry')
        model = os.environ.get('OPENAI_REALTIME_MODEL', 'gpt-realtime-2.1')
        ws = websocket.create_connection(
            'wss://api.openai.com/v1/realtime?model=' + quote(model),
            header=['Authorization: Bearer ' + os.environ['OPENAI_API_KEY']], timeout=30)
        try:
            ws.send(json.dumps({'type': 'session.update', 'session': {
                'type': 'realtime', 'output_modalities': ['audio'],
                'instructions': 'Answer naturally and concisely, usually in one or two sentences.',
                'audio': {
                    'input': {'format': {'type': 'audio/pcm', 'rate': 24000}, 'turn_detection': None},
                    'output': {'format': {'type': 'audio/pcm', 'rate': 24000},
                               'voice': os.environ.get('OPENAI_REALTIME_VOICE', 'marin')}}}}))
            deadline = time.monotonic() + 30
            while receive(ws, deadline).get('type') != 'session.updated':
                pass
        except Exception:
            ws.close()
            raise
        key = 'rt_' + uuid.uuid4().hex
        session = {'ws': ws, 'busy': True, 'used': now}
        _sessions[key] = session
        return key, session


def release(key, session, success):
    with _lock:
        if success:
            session['busy'] = False
            session['used'] = time.monotonic()
        else:
            session['ws'].close()
            _sessions.pop(key, None)


def convert_input(raw):
    with tempfile.TemporaryDirectory(prefix='n95-realtime-') as directory:
        source = Path(directory) / 'recording'
        source.write_bytes(raw)
        result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-protocol_whitelist',
            'file,pipe', '-i', str(source), '-t', '30', '-ac', '1', '-ar', '24000',
            '-f', 's16le', 'pipe:1'], capture_output=True, check=True, timeout=20)
        if len(result.stdout) < 4800:
            raise RealtimeError('Record at least a tenth of a second')
        return result.stdout


def stream_turn(raw, previous, on_ready, on_done):
    """Yield MP3 bytes. on_done runs before EOF so /reply can retrieve the text."""
    pcm = convert_input(raw)
    key, session = acquire(previous)
    ws = session['ws']
    process = None
    worker = None
    success = False
    errors = []
    transcript = []
    try:
        process = subprocess.Popen(['ffmpeg', '-nostdin', '-v', 'error',
            '-f', 's16le', '-ar', '24000', '-ac', '1', '-i', 'pipe:0',
            '-c:a', 'libmp3lame', '-b:a', '48k', '-flush_packets', '1',
            '-write_xing', '0', '-id3v2_version', '0', '-f', 'mp3', 'pipe:1'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for offset in range(0, len(pcm), 24000):
            ws.send(json.dumps({'type': 'input_audio_buffer.append',
                'audio': base64.b64encode(pcm[offset:offset + 24000]).decode()}))
        ws.send(json.dumps({'type': 'input_audio_buffer.commit'}))
        ws.send(json.dumps({'type': 'response.create'}))
        on_ready(key)

        def pump():
            try:
                deadline = time.monotonic() + 120
                audio_bytes = 0
                while True:
                    event = receive(ws, deadline)
                    kind = event.get('type')
                    if kind == 'response.output_audio.delta':
                        data = base64.b64decode(event['delta'], validate=True)
                        audio_bytes += len(data)
                        if audio_bytes > 24000 * 2 * 120:
                            raise RealtimeError('Reply exceeds two minutes')
                        process.stdin.write(data)
                        process.stdin.flush()
                    elif kind == 'response.output_audio_transcript.delta':
                        transcript.append(event['delta'])
                    elif kind == 'response.done':
                        if event['response'].get('status') != 'completed':
                            raise RealtimeError('Realtime response did not complete')
                        break
            except Exception as error:
                errors.append(error)
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass

        worker = threading.Thread(target=pump, daemon=True)
        worker.start()
        total = 0
        while True:
            chunk = process.stdout.read1(4096)
            if not chunk:
                break
            total += len(chunk)
            if total > 2097152:
                raise RealtimeError('MP3 reply exceeds size limit')
            yield chunk
        worker.join(timeout=2)
        if worker.is_alive():
            raise RealtimeError('Audio worker did not finish')
        if errors:
            raise RealtimeError(str(errors[0]))
        if process.wait(timeout=5) != 0 or not total:
            raise RealtimeError('Audio encoder returned no valid reply')
        on_done(key, ''.join(transcript) or '[Spoken reply]')
        success = True
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
        if not success:
            ws.close()
        if worker is not None:
            worker.join(timeout=3)
        release(key, session, success)
