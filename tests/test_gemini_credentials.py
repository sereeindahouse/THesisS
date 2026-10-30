"""Remembered-key and reuse contracts. No user key, Google call or human score."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gemini_credentials import WindowsCredentialStore, CredentialStoreError, _crypt
from gemini_stt_runtime import GeminiSTT, GeminiSTTError
from gemini_live_transport import LIVE_MODEL
from tools.compare_stt_candidate import CandidateError

KEY='constructed-credential-not-a-real-key-000'
CONFIG=dict(api_key=KEY,free_tier_confirmed=True,data_terms_confirmed=True,
            max_attempts=0,remember=True,continuous_use=True)

class Store:
    def __init__(self):
        self.value=None
    def save(self,value):
        self.value=copy.deepcopy(value)
    def load(self):
        return copy.deepcopy(self.value)
    def clear(self):
        self.value=None

class Transport:
    calls=0
    def __init__(self,_):
        pass
    def transcribe(self,*_,**__):
        Transport.calls+=1
        return dict(text='Зохиомол гаралт',model=LIVE_MODEL)

class CredentialSessionTests(unittest.TestCase):
    def setUp(self):
        Transport.calls=0
        self.store=Store()
        self.now=1000
        self.cloud=GeminiSTT(live_transport_factory=Transport,credential_store=self.store,clock=lambda:self.now)

    def test_remember_once_restores_new_server_without_reentering_key_or_network(self):
        self.cloud.configure(CONFIG)
        restored=GeminiSTT(live_transport_factory=Transport,credential_store=self.store)
        status=restored.status()
        self.assertTrue(status['ready'])
        self.assertTrue(status['key_persisted'])
        self.assertTrue(status['continuous_use'])
        self.assertEqual(status['available_models'],[LIVE_MODEL])
        self.assertNotIn(KEY,json.dumps(status))
        self.assertEqual(Transport.calls,0)

    def test_normal_use_does_not_ask_for_key_again_after_five_distinct_clips(self):
        self.cloud.configure(CONFIG)
        for i in range(7):
            self.cloud.transcribe(bytes([i]),consent=True,live=True)
        self.assertTrue(self.cloud.status()['ready'])
        self.assertEqual(Transport.calls,7)
        self.assertTrue(self.cloud.status()['key_persisted'])

    def test_old_open_page_configuration_cannot_erase_saved_key_or_restore_five_clip_cap(self):
        self.cloud.configure(CONFIG)
        status=self.cloud.configure(dict(api_key=KEY,free_tier_confirmed=True,
            data_terms_confirmed=True,max_attempts=5))
        self.assertTrue(status['continuous_use'])
        self.assertTrue(status['key_persisted'])
        self.assertIsNone(status['remaining_attempts'])
        self.assertEqual(self.store.load()['api_key'],KEY)
        for i in range(6):
            self.cloud.transcribe(bytes([i]),consent=True,live=True)
        self.assertTrue(self.cloud.status()['ready'])

    def test_repeated_identical_clip_reuses_raw_result_without_cloud_call(self):
        self.cloud.configure(CONFIG)
        first=self.cloud.transcribe(b'constructed-wav',consent=True,live=True)
        second=self.cloud.transcribe(b'constructed-wav',consent=True,live=True)
        self.assertFalse(first['cache_hit'])
        self.assertTrue(second['cache_hit'])
        self.assertFalse(second['provider_call_performed'])
        self.assertEqual(second['text'],first['text'])
        self.assertEqual(Transport.calls,1)
        self.assertEqual(self.cloud.status()['attempted'],1)
        with self.assertRaises(GeminiSTTError):
            self.cloud.transcribe(b'constructed-wav',consent=False,live=True)

    def test_cache_expires_and_is_cleared_when_credentials_change(self):
        self.cloud.configure(CONFIG)
        self.cloud.transcribe(b'a',consent=True,live=True)
        self.now+=1801
        self.assertFalse(self.cloud.transcribe(b'a',consent=True,live=True)['cache_hit'])
        self.cloud.configure(CONFIG)
        self.assertFalse(self.cloud.transcribe(b'a',consent=True,live=True)['cache_hit'])
        self.assertEqual(Transport.calls,3)

    def test_quota_cooldown_preserves_key_and_does_not_trigger_automatic_retry(self):
        class Limited(Transport):
            def transcribe(self,*_,**__):
                Transport.calls+=1
                raise CandidateError('http_429')
        self.cloud._live_factory=Limited
        self.cloud.configure(CONFIG)
        with self.assertRaises(GeminiSTTError):
            self.cloud.transcribe(b'a',consent=True,live=True)
        self.assertFalse(self.cloud.status()['ready'])
        self.assertTrue(self.cloud.status()['configured'])
        self.assertTrue(self.cloud.status()['key_persisted'])
        self.assertEqual(self.cloud.status()['retry_after_seconds'],60)
        self.now+=61
        self.assertTrue(self.cloud.status()['ready'])
        self.assertEqual(Transport.calls,1)

    def test_corrupt_restoration_never_exposes_secret_or_pretends_ready(self):
        class Failed(Store):
            def load(self):
                raise RuntimeError(KEY)
        cloud=GeminiSTT(credential_store=Failed())
        self.assertFalse(cloud.status()['ready'])
        self.assertEqual(cloud.status()['credential_error'],'credential_restore_failed')
        self.assertNotIn(KEY,json.dumps(cloud.status()))

    def test_forget_removes_persistent_and_memory_key(self):
        self.cloud.configure(CONFIG)
        self.cloud.clear()
        self.assertIsNone(self.store.value)
        self.assertFalse(GeminiSTT(credential_store=self.store).status()['configured'])

    def test_failed_save_leaves_previous_configuration_intact(self):
        self.cloud.configure(CONFIG)
        with patch.object(self.store,'save',side_effect=OSError(KEY)):
            with self.assertRaises(GeminiSTTError) as error:
                self.cloud.configure(dict(CONFIG,api_key='another-fixture-0000000000000'))
        self.assertNotIn(KEY,str(error.exception))
        self.assertEqual(self.cloud._key,KEY)
        self.assertTrue(self.cloud.status()['key_persisted'])

class CredentialFileTests(unittest.TestCase):
    def test_only_encrypted_bytes_written_with_atomic_replace_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'credential.dpapi';store=WindowsCredentialStore(path)
            with patch('gemini_credentials._crypt',side_effect=lambda raw,**kw: b'opaque-fixture' if not kw.get('decrypt') else json.dumps(CONFIG).encode()):
                store.save(CONFIG)
                self.assertEqual(path.read_bytes(),b'opaque-fixture')
                self.assertNotIn(KEY.encode(),path.read_bytes())
                self.assertEqual(store.load()['api_key'],KEY)
            self.assertEqual(list(Path(directory).iterdir()),[path])
            store.clear()
            self.assertIsNone(store.load())

    @unittest.skipUnless(os.name=='nt','DPAPI belongs to Windows')
    def test_native_dpapi_current_user_roundtrip(self):
        try:
            encrypted=_crypt(KEY.encode())
        except CredentialStoreError:
            self.skipTest('DPAPI blocked in sandbox; run this native check in the Windows user context')
        self.assertNotIn(KEY.encode(),encrypted)
        self.assertEqual(_crypt(encrypted,decrypt=True),KEY.encode())
