2026.10.15 нэмэлт: [clarification_context.py](../clarification_context.py) D тодруулгын
богино хариуг зөвшөөрсөн сонголттой холбодог; [demo_server.py](../demo_server.py)
API/эхийн binding-ийг дахин шалгана. [demo/index.html](../demo/index.html) raw ба
тодруулсан бүтэн асуултыг харуулж, шинэ чатад холбоосыг арилгана.
`tests/test_clarification_context.py`, `tests/test_clarification_http.py` regression.

# Гол файлуудыг нэг дороос нээх

| Хэсэг | Үндсэн файл | Үүрэг |
|---|---|---|
| Demo | [demo_server.py](../demo_server.py), [интерфэйс](../demo/index.html) | Микрофон/файл, текст засвар, чиглүүлэгч, TTS, сонсголын нэг дэлгэц |
| Нэг даралтын нээлт | [open_demo.py](../open_demo.py), [DEMO.cmd](../DEMO.cmd) | Сервер асаах/ашиглах, браузер нээх |
| Эхийн атлас ба явц | [data_explorer.py](../data_explorer.py), [интерфэйс](../demo/data.html), [шалгуурын бүртгэл](../config/project-progress.json) | 77 эх, fact/FAQ, огноо/locator, зураг/PDF preview, техникийн явц |
| Веб эхийн сан | [website_corpus.py](website_corpus.py) | Crawl, snapshot/hash, SQLite, draft эхийн хайлт |
| PDF/зургийн сонгосон эх | [document_corpus.py](document_corpus.py), [тест](../tests/test_document_corpus.py) | Эх файл/hash, хуудас/заалт, буулгалтын хувилбар |
| Эхийн хамрах хүрээний хэмжилт | [evaluate_source_retrieval.py](../tools/evaluate_source_retrieval.py), [36 асуулт](../data/rag-source-dev-20261012.json) | Зорилтот хэсэг top1/top3/top5; accuracy биш |
| Facts/FAQ сан | [content_store.py](../content_store.py), [import_content.py](../import_content.py) | Баталгаа/хугацаа/хувилбартай импорт |
| Асуултын зам | [question_router.py](../question_router.py), [тест](../tests/test_question_router.py) | Exact/он/нэр/баталгаа/тодруулга/эхгүй асуултын суурь |
| FAQ хайлт | [sqlite_retrieval.py](../sqlite_retrieval.py) | DB-ээс BM25/E5 эрэмбэ, guarded exact preview |
| Week4 reference ба автомат дуу | [40 асуулт](../data/answer-week04-dev-20261014.json), [field contract](../source_fields.py), [validator](../tools/validate_answer_cases.py), [SELF-CHECK.cmd](SELF-CHECK.cmd) | Frozen provenance, bounded field checks, 12 synthetic voice loop ба private HTML |
| Чатны RAG | [rag_runtime.py](../rag_runtime.py), [website_retrieval.py](../website_retrieval.py) | Hybrid хайлт, эхийн шууд хэсэг, локал генераци, TTS-д хариулт холбох |
| Локал генератор эхлүүлэх | [start_local_llm.py](../tools/start_local_llm.py) | Өмнө суусан project-local Ollama-г нээх; таталт хийхгүй |
| Embedding туршилт | [retrieval_probe.py](../retrieval_probe.py) | BM25/E5-ийн ижил нөхцөлийн харьцуулалт |
| Бичлэг | [record.py](../record.py) | Микрофоноор WAV бичих |
| Монгол STT | [stt_mn.py](../stt_mn.py) | Cafet жин/hash/decoder шалгаж дуу таних |
| Demo-ийн STT/TTS | [voice_runtime.py](../voice_runtime.py), [тест](../tests/test_voice_runtime.py) | Локал pinned STT, онлайн хоёр TTS хоолой, үе шатны хугацаа, түр cache/reset |
| Хүний сонсгол | [listening_review.py](../listening_review.py), [тест](../tests/test_listening_review.py) | 6 STT/3 TTS-ийн илэрхий баталгаа, hash/backup/журнал, хуучин гаралтын rescore |
| Алдааны тооцоо | [score.py](../score.py) | WER/CER |
| TTS | [tts.py](../tts.py) | Текстээс дуу |
| Агуулгын загвар | [content.schema.json](../schemas/content.schema.json), [draft data](../data/content-draft-v1.json) | Эх/fact/FAQ-ийн бүтэц |
| 3-р долоо хоногийн шийдвэр | [WEEK03-DECISIONS](WEEK03-DECISIONS.mn.md), [aggregate нотолгоо](../docs/experiments/week03-evidence-20261010.json) | Ижил оролтын чанар/хугацаа, түр сонголт, үлдсэн шалгалт |
| Моделийн багц | [release config](../config/releases/models-20261010.json), [installer](../tools/install_release_models.py) | Pinned жин ба SHA шалгаж суулгах |
| Шалгалт | [веб сангийн тест](../tests/test_website_corpus.py), [HTTP тест](../tests/test_demo_server.py) | Хувилбар/эх/draft/HTTP хамгаалалт |
| Судалгаа | [20+6 өгүүлэл](../reports/research/RESEARCH-26-PAPERS.mn.md) | Аргын сонголтын эх |
| Одоогийн үр дүн | [PROGRESS](../reports/current/PROGRESS.mn.md) | Дууссан, үлдсэн ажлын тайлан |

SQLite файлуудын локал байрлал: `CORE/database/website.db` болон `runtime/content.db`.
Веб snapshot, HTML/text/documents: `CORE/website/snapshots/`.
Үндсэн төсөл workspace-д **THesisS — код** нэрээр нээгдэнэ; concepts/data/report холбоосууд
энэ CORE хавтаст байна. Runtime/module файлуудын эх байрлал дээр ажиллана.


Шинэ дууны түр cache: `runtime/voice-demo/`; хувийн сонсголын backup/журнал
нь локал runtime-д байна. Pilot-ийн дуу, бүх зөв текст, сонсголын хувийн хүснэгт
GitHub-д орохгүй; нийтлэхийг зөвшөөрсөн q01–q03 жишээ тусдаа хэвээр.
