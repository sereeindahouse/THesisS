<!-- actual-user-followup-20261025:start -->
**2026.10.25 — Бодит хэрэглээний засвар:** 1239 локал тест тэнцсэн (144.163s). Компани/он сонгоход анхны асуулт хадгалагдах, механикийн хүснэгтэд клубийн тоо холилдох, ерөнхий асуултад хамааралгүй мэдээ өгөх алдааг засав. Brave дээр дөрвөн эцсийн үйлдэл тэнцсэн; STT-ийн дараах локал Gemma санал нь хэрэглэгчийн сонголтоор хэрэгжинэ. Raw STT **WER 36.02% хэвээр**. Өнөөдрийн 12 тохиолдол нь handling шалгалт; хүний accuracy эсвэл 12 бүрэн хариулт биш. [Явц](ROADMAP-PROGRESS.mn.md) · [Чат](http://127.0.0.1:8765/).
<!-- actual-user-followup-20261025:end -->

**10.24 — Бодит браузерээр шалгав:** модны хулганын товшилт болон багшийн нэр/танилцуулгын найруулгыг зассан. Desktop, 374/376 CSS px нарийн харагдац, дөрвөн карт/хоёр зураг ажилласан. 1148 тест PASS; RAG development23бүрэн/1partial; rawSTT36.02%хэвээр.

## 10.24 — Шинэ талбарын сонголт ба зураггүй багшийн нэр

source_fields.py-ийн structured_field_extract нь бүрэн танигдсан асуултын шаардсан мөрүүдийг эхийн бүтэцтэй тулгана; evidence_contract.py-ийн exact_field_units нь физик мөр/offset/context холбоог батална. rag_runtime.py нь тэр plan-ийг ердийн resolver-ээр шалгаж A замд харуулна. TeacherMedia v2 нь нэр/үүргийг зурагтай тусад нь баталж, text-only карт дэмжинэ. tests/test_structured_field_extract.py-ийн14контрол, tests/test_teacher_cards_ui.py-ийнжинхэнэrenderer-ийншалгалт орсон. [Эцсийнявц](ROADMAP-PROGRESS.mn.md).

<!-- rag-focus-files-20261024:start -->
## 2026.10.24 — Харагдах мэдлэгийн мод ба RAG-ийн гол файлууд

[**SVG мэдлэгийн модыг нээх →**](http://127.0.0.1:8765/data#tree) · [Модыг тайлбартай унших](KNOWLEDGE-TREE.mn.md) · [15 өгүүллийн үндэслэл](../papers/08-knowledge-tree-research.mn.md) · [Явц](ROADMAP-PROGRESS.mn.md).

Сургуулийн зураг **33 зангилаа/32 холбоостой**, системийн урсгал **16 зангилаа/19 сумтай**. Зангилааг дарж эхийг нээх, хайх, томруулах, зөөх, бүтнээр харах боломжтой. Системийн зураг нь эхээс хариулт хүртэлх өгөгдлийн урсгалыг харуулна; нейроны жин, LLM-ийн дотоод бодлыг илэрхийлэхгүй.

| Файл | Бодит үүрэг |
|---|---|
| [data.html](../demo/data.html), [data.js](../demo/data.js), [data.css](../demo/data.css) | SVG зангилаа/холбоос, харагдацын удирдлага, хайлт, гарын товчлуур болон нарийн дэлгэцийн сонголт; текстэн жагсаалт нэмэлтээр |
| [data_explorer.py](../data_explorer.py), [demo_server.py](../demo_server.py) | `/api/explorer/tree`: сонгосон хоёр DB-ийн сэдэв, тоо, албан эхийн холбоосыг зөвшөөрсөн талбараар харуулна |
| [knowledge-topics.json](../config/knowledge-topics.json), [build_knowledge_tree.py](../tools/build_knowledge_tree.py) | 33 сэдвийн санал болгосон ангилал; эх, fact/FAQ-г read-only байдлаар холбоно |
| [website_corpus.py](website_corpus.py), [website_retrieval.py](../website_retrieval.py), [evidence_contract.py](../evidence_contract.py) | HTML-ийн баталгаатай зааг, хайлт, эхийн байрлал |
| [source_fields.py](../source_fields.py), [rag_runtime.py](../rag_runtime.py) | Gemma-ийн эхийн ID сонголт, талбар/субъект/нөхцөлийн шалгалт, серверийн үгчлэн хариулт |
| [test_knowledge_graph_ui.py](../tests/test_knowledge_graph_ui.py), [knowledge_graph_ui_harness.js](../tests/knowledge_graph_ui_harness.js) | Public 33 сэдвийн зохиомол туршилтын өгөгдөл; зангилаа/холбоос, эх хүрэх, харагдац удирдах, хүртээмжийн шалгалт |
| [test_knowledge_tree.py](../tests/test_knowledge_tree.py), [test_data_explorer.py](../tests/test_data_explorer.py) | Эхийн бүртгэл, read-only экспорт, хувийн талбар/URL хамгаалалт, active хувилбар солигдох үеийн хориг |

1124 локал автомат тест тэнцсэн. Бодит API-ийн өгөгдлөөр DOM дуурайлгасан орчинд байрлал, холбоос, удирдлагын 13 нөхцөл тэнцэж, графын байрлалаас PNG preview гарган үзсэн. Эдгээр нь бодит браузерийн screenshot, хараат бус хүний accuracy биш.
<!-- rag-focus-files-20261024:end -->

<!-- answer-refinement-files-20261022:start -->
## Одоогийн үндсэн хэсгүүд — 2026.10.22

**981 тест тэнцсэн код [чатад](http://127.0.0.1:8765/) ажиллаж байна.** Шинэ 26 API асуултын регрессийг шалгасан; энэ нь 26/26 accuracy гэсэн үг биш.

| Хэсэг | Энэ удаа юу сайжирсан бэ? | Гол файл |
|---|---|---|
| RAG | Нэг физик эхийн давхцлыг давтаж харуулахгүй | [evidence_contract.py](../evidence_contract.py) |
| LLM-ийн дараах шалгалт | Хоёр хязгаарласан асуултын хэлбэрт хэрэггүй сонголтыг бүх guard-аар дахин шалгаж хасна | [rag_runtime.py](../rag_runtime.py), [source_fields.py](../source_fields.py) |
| STT-ийн хэрэглээ | 120 секундийн browser wait, retry/reset, хуучин хариунаас хамгаалалт | [index.html](../demo/index.html) |
| TTS ба өгөгдлийн хувилбар | Эх солигдсон үед үүссэн илүү аудиог цэвэрлэнэ | [demo_server.py](../demo_server.py) |
| Дахин шалгах | Эх/нөхцөл алдахгүй байдал, жинхэнэ JS handler, release race | [test_answer_refinement.py](../tests/test_answer_refinement.py), [test_voice_ui_recovery.py](../tests/test_voice_ui_recovery.py), [test_content_release_http.py](../tests/test_content_release_http.py) |

Ижил 16 хариултын fixed-root туршилтад унших текст 9009→7934 тэмдэгт. Raw STT WER 36.02% хэвээр; шинэ хүний accuracy биш. [Явц ба хязгаар](ROADMAP-PROGRESS.mn.md) · [Gemma/RAG арга](CONCEPTS.mn.md).
<!-- answer-refinement-files-20261022:end -->

<!-- audit-fix-files-20261022:start -->
## Одоогийн шалгасан хувилбар — 2026.10.22

**949 тест тэнцсэн код [чатад](http://127.0.0.1:8765/) ажиллана.** Аудитын гурван доголдол, түүхийн буруу үйл явдал сонгосон тохиолдлыг зассан.26бодит асуулт/34үгчлэн эшлэл шалгасан; энэ нь26/26accuracy биш.

- [website_retrieval.py](../website_retrieval.py): дундаасаа тасарсан үгтэй хэсгийг санал болгохгүй, бүтэн физик мөрийн зааг хэрэглэнэ.
- [evidence_contract.py](../evidence_contract.py): хасагдсан paragraph дээгүүр context холбохгүй; компанийн нэр–тайлбарын залгаа холбоог хадгална.
- [source_fields.py](../source_fields.py): хэлбэрийн хүсэлт талбарын шалгалтыг арилгахгүй; сургуулийн үүсэлтийн нэг үйл явдалд он/өдөр/тоог холбоно.
- [test_history_evidence.py](../tests/test_history_evidence.py), [test_structure_context.py](../tests/test_structure_context.py): өөр объект, нөхцөл, няцаалт, тасарсан холбооны сорил.
- [Gemma ба RAG-ийг дипломд зөв тайлбарлах](CONCEPTS.mn.md) · [Бодит дүн ба хязгаар](ROADMAP-PROGRESS.mn.md).

RawSTT WER36.02%хэвээр. Индекс196хэсэг; эхDB,40fact/30FAQөөрчлөгдөөгүй. Диплом бүхэлдээ дууссан гэж тайлагнаагүй.
<!-- audit-fix-files-20261022:end -->

<!-- core-next-files-20261021:start -->
## Хамгийн сүүлийн код ба GitHub-д нийтлэх хувилбар

**897 тест тэнцсэн код [чатад](http://127.0.0.1:8765/) ажиллаж байна.** Өмнө үлдсэн чиглэл–нэр, хичээл–онлайн хэлбэрийн хоёр omission ижил development багц дээр засагдсан: Gemma AI бүрэн8/8, best3 мөн8/8. Хүний шинэ accuracy биш; давталт/хамааралгүй хэсэг үлдсэн.

- [evidence_contract.py](../evidence_contract.py): эхийн diagram-card болон компанийн гарчигтай дараагийн өгүүлбэрийн холбоог хадгална.
- [source_fields.py](../source_fields.py): хоёр чиглэл–нэрийн холбоо, нэрлэсэн хичээлүүдийн хэрэгжсэн хэлбэрийг шаардана.
- [test_structure_context.py](../tests/test_structure_context.py): өөр компанийн өгүүлбэр, үгүйсгэл, дутуу хос, budget-ийн15 control.
- [RAG-ийг энгийнээр ойлгох](CONCEPTS.mn.md) · [Хэмжилт/хязгаар](ROADMAP-PROGRESS.mn.md).

STT-ийн хамгаалалттай дөрвөн гаралтын туршилт WER бууруулаагүй тул нэвтрүүлээгүй. Raw WER36.02% хэвээр. Код GitHub-д нийтлэгдэхэд хувийн аудио, transcript, модель, DB, runtime үр дүн хамт орохгүй; q01–q03-ийн өмнө зөвшөөрсөн demo хувилбар л public.
<!-- core-next-files-20261021:end -->

<!-- rag-completeness-files-20261021:start -->
## Одоогийн RAG засвар ба шалгах файлууд

**882 тест, бодит 10 HTTP шалгалт тэнцсэн код [чатад](http://127.0.0.1:8765/) ачаалагдсан.** Ижил 8 асуултын Gemma хариултын бүрэн байдал AI development үнэлгээгээр 4/8→6/8; хүний шинэ accuracy биш. [Хэмжилт ба хязгаар](ROADMAP-PROGRESS.mn.md).

| Файл | Энэ удаагийн өөрчлөлт |
|---|---|
| [evidence_contract.py](../evidence_contract.py) | Эхийн `•` жагсаалтын том үсэгтэй мөрийг шинэ гарчиг гэж таслахгүй |
| [rag_runtime.py](../rag_runtime.py) | Онтой мэдээлэл дутвал шалгагдсан нэг/хоёр эхийн хэсгээс нэг удаа дахин сонгуулна |
| [source_fields.py](../source_fields.py) | Хоёр төрлийн дадлага асуувал тус бүрийн нэрлэсэн жагсаалтыг шаардана; үгүйсгэлийг эерэг баталгаа болгохгүй |
| [Туршилтын бүртгэл](../runtime/rag-completeness-20261021/README.mn.md) | Анхны ба дараах гаралт, AI үнэлгээ, регрессийн өртөг, бодит серверийн нотолгоо |

Хүний өмнөх 49 event хадгалагдсан. Raw STT WER 36.02% хэвээр; энэ засварыг танилтын чанарын өсөлт гэж тооцохгүй. Доорх огноотой тестийн тоонууд өмнөх checkpoint-үүдийнх.
<!-- rag-completeness-files-20261021:end -->

<!-- human-feedback-files-20261021:start -->
## Хүний дүн ба засварын одоогийн холбоос

[Нэгтгэсэн дүн](ROADMAP-PROGRESS.mn.md): нэг хөгжүүлэгчийн12сонсгол,24хариулт,нэг task хадгалагдсан. Эх үнэлгээг засварын дараах шинэ үр дүнгээр дарж өөрчлөөгүй.
[website_retrieval.py](../website_retrieval.py) нь exact search spelling alias хэрэглэнэ; query/raw STT хэвээр.
[speech_text.py](../speech_text.py) нь зөвхөн ЕБС/ЕБС-ийн гэсэн2хэлбэрийг дуугаар бүтэн уншина.
[manage_content_release.py](../tools/manage_content_release.py) дэх stage-code-upgrade нь хуучин sealed өгөгдлийг байтаар нь шалгаад шинэ ноорогт хуулна; validate/publish тусдаа. Автоматаар хуучин hash-ийг зөвшөөрөхгүй.
<!-- human-feedback-files-20261021:end -->

<!-- quality-media-files-20261021:start -->
## Одоо ажиллаж буй зураг ба чанарын шалгалтын файлууд

[Чат](http://127.0.0.1:8765/) · [Хүний үнэлгээ](http://127.0.0.1:8790/) · [Үнэлгээний заавар](HUMAN-QUALITY-CHECK.mn.md).
Чатад «Соронзонболд багшийн зурагтай танилцуулга үзье» гэж асууна. Батчулуун багшийн зураг мөн бий. Хоёр хүний албан эхэд байх мэдээллийг л харуулна.

| Файл | Бодит үүрэг |
|---|---|
| [teacher_media.py](../teacher_media.py) | Албан бүтэцтэй нэр–зураг холбоос, эх/зургийн SHA, огноо, хязгаарласан асуултын шалгалт; placeholder/буруу capture-д зураг өгөхгүй |
| [demo_server.py](../demo_server.py), [чат](../demo/index.html) | Нэр тодруулах, зурагтай карт, эхийн холбоос, тухайн хариултын TTS |
| [evaluate_llm_selection.py](../tools/evaluate_llm_selection.py) | Ижил frozen эх дээр Gemma ба LLM-гүй1/3 хэсгийн сонголтыг ижил guard-тай харьцуулна |
| [human_quality_trial.py](../tools/human_quality_trial.py) | 24 хариултын арга нуусан үнэлгээ,12дуу,typed/raw/edited даалгавар; бодит хүний үр дүнг өөрөө нөхөхгүй |

**841 тест PASS** нь ажиллагааны баталгаа; хариултын хүний accuracy биш. LLM-ийн жижиг туршилт Gemma-ийн давуу талыг батлаагүй. RawSTT WER36.02% хэвээр. [Дүн ба хязгаар](ROADMAP-PROGRESS.mn.md).
<!-- quality-media-files-20261021:end -->

<!-- delivery-files-20261021:start -->
## 2026.10.21 — Шинээр хэрэгжүүлсэн гол файлууд

| Хэрэгцээ | Файл | Одоо юу хийдэг вэ? |
|---|---|---|
| Мэдээлэл шинэчлэх | [ADMIN.cmd](ADMIN.cmd), [заавар](ADMIN-GUIDE.mn.md), [admin.js](../demo/admin.js) | Ноорог, эхтэй diff, нийтлэх, өмнөх хувилбарт буцаах |
| Өгөгдлийн хувилбар | [content_release.py](../content_release.py), [release_runtime.py](../release_runtime.py) | Hash-тай sealed хоёрDB, atomic active pointer, хуучин хүсэлтийн хориг |
| Командын шинэчлэлт | [manage_content_release.py](../tools/manage_content_release.py) | Stage/import/validate/publish/rollback |
| STT эх ба засвар | [voice_runtime.py](../voice_runtime.py), [demo_server.py](../demo_server.py) | Серверийн transcriptionID-тай raw/edited lineage, асуулт бүрийн тусдаа бичвэр |
| TTS унших хэлбэр | [speech_text.py](../speech_text.py), [харьцуулалт](../tools/evaluate_speech_delivery.py) | Хязгаарласан он/утас/мөнгөн дүн; дэлгэцийн эхийг өөрчлөхгүй |
| Хүргэлтийн бэлэн байдал | [check_delivery_readiness.py](../tools/check_delivery_readiness.py) | Dependency/model SHA, эхийн integrity, public/private зам; network/inferenceгүй |

[Бодит үр дүн, үлдсэн хязгаар](ROADMAP-PROGRESS.mn.md). Доорх огноотой тоонууд түүхэн checkpoint.
<!-- delivery-files-20261021:end -->

2026.10.16 STT: [offline comparison CLI](../tools/evaluate_stt_context.py),
[туршилтын arms](../config/stt-context-development.json), [тест](../tests/test_stt_context.py).
[voice_runtime.py](../voice_runtime.py) presence-only gate+loaded provenance;
[voice collector](../tools/evaluate_voice_loop.py) хуучин STT code-г эхлэхээс өмнө хаана.

2026.10.15 V6: [evidence_contract.py](../evidence_contract.py) exact span/context;
[source_fields.py](../source_fields.py) literal field/scope/ambiguity;
[rag_runtime.py](../rag_runtime.py) bounded replacement+active-ID guards.
568 тест;40 observed development review ба хязгаар: [явц](ROADMAP-PROGRESS.mn.md).

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
| Эхийн атлас ба явц | [data_explorer.py](../data_explorer.py), [интерфэйс](../demo/data.html), [шалгуурын бүртгэл](../config/project-progress.json) | 75 HTML+5 баримтын эх, fact/FAQ, огноо/locator, зураг/PDF preview, техникийн явц |
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
