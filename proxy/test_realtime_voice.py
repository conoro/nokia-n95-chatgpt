import base64
import io
import json
import unittest
import wave
from unittest.mock import patch

from realtime_voice import RealtimeError, stream_turn


def fixture():
    result = io.BytesIO()
    with wave.open(result, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\0\0' * 24000)
    return result.getvalue()


class FakeSocket:
    def __init__(self, fail=False):
        self.sent = []
        self.closed = False
        self.events = [{'type': 'response.output_audio.delta',
                        'delta': base64.b64encode(b'\0\0' * 24000).decode()} for _ in range(3)]
        self.events += [{'type': 'response.output_audio_transcript.delta', 'delta': 'Hello'},
                        {'type': 'response.done', 'response': {'status': 'completed'}}]
        if fail:
            self.events = [{'type': 'error', 'error': {'code': 'test_error'}}]
    def send(self, data):
        self.sent.append(json.loads(data))
    def recv(self):
        return json.dumps(self.events.pop(0))
    def settimeout(self, timeout):
        pass
    def close(self):
        self.closed = True


class RealtimeTest(unittest.TestCase):
    def test_audio_turn_and_transcript(self):
        ws = FakeSocket()
        session = {'ws': ws}
        done = []
        with patch('realtime_voice.acquire', return_value=('rt_test', session)), patch('realtime_voice.release') as release:
            data = b''.join(stream_turn(fixture(), '', lambda key: None,
                                       lambda key, text: done.append((key, text))))
            self.assertGreater(len(data), 1000)
            self.assertEqual(done, [('rt_test', 'Hello')])
            self.assertEqual(ws.sent[-2:], [{'type': 'input_audio_buffer.commit'}, {'type': 'response.create'}])
            self.assertTrue(any(event['type'] == 'input_audio_buffer.append' for event in ws.sent))
            release.assert_called_once_with('rt_test', session, True)

    def test_upstream_error_discards_session(self):
        ws = FakeSocket(fail=True)
        session = {'ws': ws}
        with patch('realtime_voice.acquire', return_value=('rt_test', session)), patch('realtime_voice.release') as release:
            with self.assertRaises(RealtimeError):
                list(stream_turn(fixture(), '', lambda key: None, lambda key, text: None))
            self.assertTrue(ws.closed)
            release.assert_called_once_with('rt_test', session, False)
