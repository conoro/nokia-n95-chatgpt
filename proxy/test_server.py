import io
import http.client
import wave
import json
import os
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from server import Handler


class BridgeTest(unittest.TestCase):
    def test_speech_arrives_before_upstream_finishes(self):
        release = threading.Event()
        waiting = threading.Event()
        class IncrementalAudio(io.BytesIO):
            def __init__(self):
                super().__init__()
                self.calls = 0
            def read1(self, size):
                self.calls += 1
                if self.calls == 1:
                    return b'first-audio'
                if self.calls == 2:
                    waiting.set()
                    if not release.wait(5):
                        raise OSError('Test timed out waiting for consumer')
                    return b'last-audio'
                return b''
        with patch.dict(os.environ, BRIDGE_TOKEN='test-token', OPENAI_API_KEY='fake'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                with patch('server.urllib.request.urlopen', return_value=IncrementalAudio()):
                    connection.request('POST', '/speak-stream', b'Hello', {'X-Bridge-Token': 'test-token'})
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIsNone(response.getheader('Content-Length'))
                    self.assertEqual(response.read(11), b'first-audio')
                    self.assertTrue(waiting.wait(2))
                    release.set()
                    self.assertEqual(response.read(), b'last-audio')
            finally:
                release.set()
                connection.close()
                server.shutdown()
                server.server_close()
                thread.join()

    def test_chat_flow(self):
        with patch.dict(os.environ, BRIDGE_TOKEN='test-token', OPENAI_API_KEY='fake', OPENAI_MODEL='test-model'):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = 'http://127.0.0.1:%d/chat' % server.server_port
            try:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(url, data=b'hello'))
                self.assertEqual(error.exception.code, 401)
                error.exception.close()
                real_open = urllib.request.urlopen
                captured = []
                def upstream(request, **kwargs):
                    if request.full_url.startswith('https://api.openai.com/'):
                        if request.full_url.endswith('/audio/speech'):
                            payload = json.loads(request.data)
                            self.assertEqual(payload['input'], 'Hello from the N95')
                            self.assertEqual(payload['response_format'], 'mp3')
                            return io.BytesIO(b'ID3-test-audio')
                        if request.full_url.endswith('/audio/transcriptions'):
                            self.assertIn(b'filename="speech.wav"', request.data)
                            self.assertIn(b'RIFF', request.data)
                            return io.BytesIO(b'{"text": "Voice message"}')
                        captured.append(json.loads(request.data))
                        return io.BytesIO(json.dumps({'id': 'resp_next', 'output': [
                            {'content': [{'type': 'output_text', 'text': 'Hello, café!'}]}]}).encode())
                    return real_open(request, **kwargs)
                with patch('urllib.request.urlopen', side_effect=upstream):
                    request = urllib.request.Request(url, data='Hi café'.encode(), headers={
                        'X-Bridge-Token': 'test-token', 'X-Response-Id': 'resp_previous'})
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.read().decode(), 'Hello, café!')
                        self.assertEqual(response.headers['X-Response-Id'], 'resp_next')
                with patch('urllib.request.urlopen', side_effect=upstream):
                    request = urllib.request.Request(url.replace('/chat', '/speak'),
                        data=b'Hello from the N95', headers={'X-Bridge-Token': 'test-token'})
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.headers['Content-Type'], 'audio/mpeg')
                        self.assertEqual(response.read(), b'ID3-test-audio')
                audio = io.BytesIO()
                with wave.open(audio, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(8000)
                    wav.writeframes(b'\0\0' * 8000)
                with patch('urllib.request.urlopen', side_effect=upstream):
                    request = urllib.request.Request(url.replace('/chat', '/transcribe'),
                        data=audio.getvalue(), headers={'X-Bridge-Token': 'test-token'})
                    with urllib.request.urlopen(request) as response:
                        self.assertEqual(response.read(), b'Voice message')
                with self.assertRaises(urllib.error.HTTPError) as invalid:
                    real_open(urllib.request.Request(url.replace('/chat', '/transcribe'),
                        data=b'bad audio', headers={'X-Bridge-Token': 'test-token'}))
                self.assertEqual(invalid.exception.code, 422)
                invalid.exception.close()
                self.assertEqual(captured[0]['previous_response_id'], 'resp_previous')
                self.assertEqual(captured[0]['input'], 'Hi café')
                with self.assertRaises(urllib.error.HTTPError) as error:
                    real_open(urllib.request.Request(url, data=b' ', headers={'X-Bridge-Token': 'test-token'}))
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
