"""Select one sealed content pair per request while sharing installed models."""
from dataclasses import dataclass
from pathlib import Path
import threading

from content_release import ContentReleaseManager
from data_explorer import SourceExplorer
from rag_runtime import ChatRAG
from website_retrieval import WebsiteRetriever
from clarification_context import ClarificationContext


@dataclass(frozen=True)
class ContentBundle:
    database: Path
    website_database: Path
    rag: object
    explorer: object
    clarification: object
    release: object = None

    @property
    def token(self):
        return self.release['activation_token'] if self.release else None

    def public(self):
        if self.release is None:
            return {'mode': 'legacy', 'release_id': None, 'activation_token': None,
                    'label': 'Анхны эхийн сан'}
        return {**{key: self.release[key] for key in
                    ('release_id', 'activation_token', 'label', 'activated_utc', 'corpus_id', 'package_id')},
                'mode': 'published'}


class LiveContentRuntime:
    def __init__(self, root, database, rag, explorer, policy, manager=None, clarification=None):
        self.root = Path(root).resolve()
        self.manager = manager or ContentReleaseManager(self.root)
        self.policy = policy
        self.legacy = ContentBundle(Path(database), self.root / 'CORE/database/website.db', rag, explorer,
                                    clarification if clarification is not None else ClarificationContext())
        self._current = None
        self._lock = threading.RLock()

    def snapshot(self):
        # resolve fails closed if a configured active release is damaged/deleted.
        active = self.manager.resolve()
        if active is None:
            return self.legacy
        with self._lock:
            if self._current is not None and self._current.token == active['activation_token']:
                return self._current
            database = Path(active['content_database'])
            website_database = Path(active['website_database'])
            retriever = WebsiteRetriever(root=self.root, database=website_database)
            # Generator has its own bounded concurrency lock. Model weights and
            # provider stay in the project; release data never includes them.
            generator = getattr(self.legacy.rag, 'generator', None)
            rag = ChatRAG(self.root, self.policy, retriever=retriever, generator=generator)
            explorer = SourceExplorer(self.root, database=website_database, content_database=database)
            bundle = ContentBundle(database, website_database, rag, explorer, ClarificationContext(), active)
            self._current = bundle
            return bundle

    def is_current(self, bundle):
        active = self.manager.resolve()
        return bundle.token == (active['activation_token'] if active else None)
