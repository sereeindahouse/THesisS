# Гол файлуудыг нэг дороос нээх

| Хэсэг | Үндсэн файл | Үүрэг |
|---|---|---|
| Demo | [demo_server.py](../demo_server.py), [интерфэйс](../demo/index.html) | Бичгэн хайлт, эхтэй preview, дууны жишээ |
| Нэг даралтын нээлт | [open_demo.py](../open_demo.py), [DEMO.cmd](../DEMO.cmd) | Сервер асаах/ашиглах, браузер нээх |
| Веб эхийн сан | [website_corpus.py](website_corpus.py) | Crawl, snapshot/hash, SQLite, draft эхийн хайлт |
| Facts/FAQ сан | [content_store.py](../content_store.py), [import_content.py](../import_content.py) | Баталгаа/хугацаа/хувилбартай импорт |
| FAQ хайлт | [sqlite_retrieval.py](../sqlite_retrieval.py) | DB-ээс BM25/E5 эрэмбэ, guarded exact preview |
| Embedding туршилт | [retrieval_probe.py](../retrieval_probe.py) | BM25/E5-ийн ижил нөхцөлийн харьцуулалт |
| Бичлэг | [record.py](../record.py) | Микрофоноор WAV бичих |
| Монгол STT | [stt_mn.py](../stt_mn.py) | Cafet жин/hash/decoder шалгаж дуу таних |
| Алдааны тооцоо | [score.py](../score.py) | WER/CER |
| TTS | [tts.py](../tts.py) | Текстээс дуу |
| Агуулгын загвар | [content.schema.json](../schemas/content.schema.json), [draft data](../data/content-draft-v1.json) | Эх/fact/FAQ-ийн бүтэц |
| Моделийн багц | [release config](../config/releases/models-20261010.json), [installer](../tools/install_release_models.py) | Pinned жин ба SHA шалгаж суулгах |
| Шалгалт | [веб сангийн тест](../tests/test_website_corpus.py), [HTTP тест](../tests/test_demo_server.py) | Хувилбар/эх/draft/HTTP хамгаалалт |
| Судалгаа | [20+6 өгүүлэл](../reports/research/RESEARCH-26-PAPERS.mn.md) | Аргын сонголтын эх |
| Одоогийн үр дүн | [PROGRESS](../reports/current/PROGRESS.mn.md) | Дууссан, үлдсэн ажлын тайлан |

SQLite файлуудын локал байрлал: `CORE/database/website.db` болон `runtime/content.db`.
Веб snapshot, HTML/text/documents: `CORE/website/snapshots/`.
Үндсэн төсөл workspace-д **THesisS — код** нэрээр нээгдэнэ; concepts/data/report холбоосууд
энэ CORE хавтаст байна. Runtime/module файлуудын эх байрлал дээр ажиллана.
