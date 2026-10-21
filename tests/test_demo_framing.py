"""Real raw loopback HTTP regression; no model, school database or personal audio."""
from contextlib import redirect_stderr
import http.client
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from demo_server import make_server
from voice_runtime import MAX_AUDIO_BYTES


class DemoFramingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.calls=[]
        owner=self
        class Voice:
            def transcribe(self,data,mime):
                owner.calls.append((data,mime))
                return dict(text='fixture',reference_confirmed=False)
        self.server=make_server(self.root/'absent.db',port=0,project_root=self.root,voice_service=Voice())
        self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)

    def request(self,path,fields,body=b'',*,host=None,origin=None):
        headers=[f'POST {path} HTTP/1.1',f'Host: {host or "127.0.0.1:"+str(self.port)}',
                 'Content-Type: audio/wav','Connection: close',*fields]
        if origin is not None:headers.append('Origin: '+origin)
        packet=('\r\n'.join(headers)+'\r\n\r\n').encode('latin-1')+body
        with socket.create_connection(('127.0.0.1',self.port),timeout=2) as client:
            client.sendall(packet)
            response=http.client.HTTPResponse(client);response.begin()
            return response.status,dict(response.getheaders()),json.loads(response.read())

    def test_non_ascii_and_pathological_decimal_lengths_return_json_without_inference(self):
        logs=io.StringIO()
        with redirect_stderr(logs):
            for value in ('²','9'*5000,'00000000000','-1','+2','2,2'):
                with self.subTest(length=value[:30]):
                    status,headers,result=self.request('/api/voice/transcribe',['Content-Length: '+value])
                    self.assertEqual(status,400)
                    self.assertIn('error',result)
                    self.assertEqual(headers['Connection'],'close')
        self.assertEqual(logs.getvalue(),'')
        self.assertEqual(self.calls,[])

    def test_early_error_drain_preserves_host_origin_and_unknown_api_status_for_invalid_lengths(self):
        logs=io.StringIO()
        with redirect_stderr(logs):
            for value in ('²','9'*5000):
                for path,kwargs,expected in (
                    ('/api/voice/transcribe',dict(host='attacker.invalid'),403),
                    ('/api/voice/transcribe',dict(origin='https://attacker.invalid'),403),
                    ('/api/not-a-route',{},404)):
                    with self.subTest(length=value[:20],path=path,kwargs=kwargs):
                        status,_,body=self.request(path,['Content-Length: '+value],**kwargs)
                        self.assertEqual(status,expected);self.assertIn('error',body)
        self.assertEqual(logs.getvalue(),'');self.assertEqual(self.calls,[])

    def test_ambiguous_lengths_and_transfer_encoding_never_reach_voice(self):
        for fields in (['Content-Length: 2','Content-Length: 2'],
                       ['Content-Length: 2','Content-Length: 3'],
                       ['Content-Length: 2','Transfer-Encoding: chunked'],
                       ['Content-Length: 2','Transfer-Encoding:']):
            with self.subTest(fields=fields):
                status,_,body=self.request('/api/voice/transcribe',fields,b'{}')
                self.assertEqual(status,400);self.assertIn('error',body)
        self.assertEqual(self.calls,[])

    def test_existing_upload_limits_and_small_bounded_rejection_drain_stay_intact(self):
        for length in ('0',str(MAX_AUDIO_BYTES+1)):
            self.assertEqual(self.request('/api/voice/transcribe',['Content-Length: '+length])[0],400)
        # The unknown route cannot wait the normal15s body timeout or infer.
        self.assertEqual(self.request('/api/not-a-route',['Content-Length: 65536'],b'{}')[0],404)
        self.assertEqual(self.calls,[])
        body=b'fixture-audio'
        status,_,result=self.request('/api/voice/transcribe',['Content-Length: '+str(len(body))],body)
        self.assertEqual(status,200);self.assertEqual(result['text'],'fixture')
        self.assertEqual(self.calls,[(body,'audio/wav')])


if __name__=='__main__':unittest.main()
