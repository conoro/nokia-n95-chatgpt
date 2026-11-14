"""Small LAN bridge for the N95 MIDlet. Uses only Python's standard library."""
import hmac
import json
import os
import shlex
import subprocess
import tempfile
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def load_env(path):
    """Load literal KEY=value settings, preserving existing environment values."""
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        name, separator, value = line.partition('=')
        name = name.strip()
        if not separator or not name.isidentifier() or not name.isascii():
            raise SystemExit('Invalid setting in .env at line %d' % number)
        try:
            parts = shlex.split(value, comments=True)
        except ValueError:
            raise SystemExit('Invalid quoting in .env at line %d' % number)
        if len(parts) > 1:
            raise SystemExit('Quote values containing spaces in .env at line %d' % number)
        os.environ.setdefault(name, parts[0] if parts else '')


def transcribe(raw):
    """Normalize handset audio (including AMR) to mono WAV before upload."""
    with tempfile.TemporaryDirectory(prefix='n95-audio-') as directory:
        source = Path(directory) / 'recording'
        target = Path(directory) / 'speech.wav'
        source.write_bytes(raw)
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y',
                        '-protocol_whitelist', 'file,pipe', '-i', str(source),
                        '-t', '30', '-ac', '1', '-ar', '16000', str(target)],
                       check=True, capture_output=True, timeout=20)
        audio = target.read_bytes()
    boundary = uuid.uuid4().hex
    model = os.environ.get('OPENAI_TRANSCRIBE_MODEL', 'gpt-4o-mini-transcribe')
    body = (('--' + boundary + '\r\nContent-Disposition: form-data; name="model"\r\n\r\n'
             + model + '\r\n--' + boundary + '\r\nContent-Disposition: form-data; '
             'name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()
            + audio + ('\r\n--' + boundary + '--\r\n').encode())
    request = urllib.request.Request('https://api.openai.com/v1/audio/transcriptions', data=body,
        headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'],
                 'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.load(response)['text'].strip()


def speak(text):
    request = urllib.request.Request('https://api.openai.com/v1/audio/speech',
        data=json.dumps({'model': os.environ.get('OPENAI_TTS_MODEL', 'gpt-4o-mini-tts'),
                         'voice': os.environ.get('OPENAI_TTS_VOICE', 'alloy'),
                         'input': text, 'response_format': 'mp3'}).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'],
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        audio = response.read(2097153)
    if len(audio) > 2097152:
        raise ValueError('Speech response too large')
    return audio


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, text, previous='', content_type='text/plain; charset=utf-8'):
        body = text if isinstance(text, bytes) else text.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if previous:
            self.send_header('X-Response-Id', previous)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200 if self.path == '/health' else 404,
                   'N95 bridge ready' if self.path == '/health' else 'Not found')

    def do_POST(self):
        if self.path not in ('/chat', '/transcribe', '/speak'):
            return self.reply(404, 'Not found')
        if not hmac.compare_digest(self.headers.get('X-Bridge-Token', ''), os.environ['BRIDGE_TOKEN']):
            return self.reply(401, 'Incorrect bridge token')
        try:
            length = int(self.headers.get('Content-Length', '0'))
            limit = 2097152 if self.path == '/transcribe' else 8192
            if not 0 < length <= limit:
                return self.reply(413, 'Request size must be between 1 and %d bytes' % limit)
            self.connection.settimeout(120)
            raw = self.rfile.read(length)
            if len(raw) != length:
                return self.reply(400, 'Incomplete request')
            if self.path == '/transcribe':
                text = transcribe(raw)
                return self.reply(200 if text else 422, text or 'No speech detected')
            prompt = raw.decode('utf-8').strip()
            if not prompt:
                return self.reply(400, 'Enter a message')
            if self.path == '/speak':
                if len(prompt) > 4096:
                    return self.reply(413, 'Speech text exceeds 4096 characters')
                return self.reply(200, speak(prompt), content_type='audio/mpeg')
            request = {'model': os.environ['OPENAI_MODEL'], 'input': prompt,
                       'max_output_tokens': 800, 'store': True,
                       'instructions': 'Answer concisely in plain text for a small phone screen.'}
            previous = self.headers.get('X-Response-Id', '')
            if previous:
                request['previous_response_id'] = previous
            upstream = urllib.request.Request(
                'https://api.openai.com/v1/responses',
                data=json.dumps(request).encode(),
                headers={'Authorization': 'Bearer ' + os.environ['OPENAI_API_KEY'],
                         'Content-Type': 'application/json'})
            with urllib.request.urlopen(upstream, timeout=90) as response:
                result = json.load(response)
            answer = '\n'.join(part['text'] for item in result.get('output', [])
                               for part in item.get('content', [])
                               if part.get('type') == 'output_text')
            if not answer:
                return self.reply(502, 'OpenAI returned no text. Start a new conversation or try again.')
            self.reply(200, answer, result['id'])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            self.reply(422, 'Could not decode recording. Try a shorter clip.')
        except (ValueError, UnicodeError):
            self.reply(400, 'Invalid request')
        except urllib.error.HTTPError as error:
            self.reply(502, 'OpenAI HTTP error %s. Check the API key, model, and quota on the bridge.' % error.code)
        except (OSError, KeyError):
            self.reply(502, 'Bridge could not obtain a reply. Check its configuration and network.')

    def log_message(self, fmt, *args):
        # Request paths and status only. Never log prompts or credentials.
        super().log_message(fmt, *args)


if __name__ == '__main__':
    load_env(Path(__file__).resolve().parent.parent / '.env')
    for name in ('OPENAI_API_KEY', 'OPENAI_MODEL', 'BRIDGE_TOKEN'):
        if not os.environ.get(name):
            raise SystemExit('Set ' + name + ' in .env before starting the bridge')
    server = ThreadingHTTPServer((os.environ.get('BRIDGE_HOST', '127.0.0.1'),
                                 int(os.environ.get('BRIDGE_PORT', '8095'))), Handler)
    print('N95 bridge listening on', server.server_address, flush=True)
    server.serve_forever()
