# Эхийн сангийн одоогийн төлөв — 2026.10.15

| Хэмжүүр | Өмнө | Одоо |
|---|---:|---:|
| HTML хуудас | 72 | 75 |
| PDF/PNG баримт | 5 | 5 |
| Анхны HTML chunk | 153 | 164 |
| Хайлтын үндсэн HTML хэсэг | 139 | 150 |
| Баримтын сонгосон заалт | 21 | 21 |
| Тэнхимийн нэмэлт табын хэсэг | 0 | 30 |
| Нийт RAG хэсэг | 160 | 201 |
| Бүтэцтэй баримт / FAQ | 10 / 5 | 40 / 30 |

3 шинэ about хуудас, 6 дахин татсан тэнхим: нийт9 HTTP200. 66 хуучин HTML ба
5 баримтын анхны татсан огноо хэвээр. Local2026.10.15-ны шинэ таталтын UTC нь
2026.10.14; атлас ISO огноог харуулна. Зорилго/зорилтын JSON, амжилтын HTML-г
хадгалсан Next Flight өгөгдлөөс JavaScript ажиллуулахгүй задална. Exact HTMLhash,
JSON pointer/text record, normalizedfieldhash, offset-г шалгана. 12 placeholder/
огноогүй үзүүлэлтийг omission бүртгэлд үлдээсэн; бүх таб/OCR хамрагдсан гэсэн үг биш.
Үндсэн HTML-ийн counter/хуучин эхийн агуулгын зөрчил автоматаар засагдаагүй.

14 source record нь11өөрURL-ийн хувилбарууд. v1-г хадгалж v2-д шинэ фактын
багц нэмсэн. Батлагдаагүй хүчинтэй хугацаа, сургуулийн хүний approval зохиогоогүй.
Хэрэглэгчийн албан эх ашиглах шийдвэр хүчинтэй; тэр зөвшөөрлийг дахин шаардахгүй.

Харах: [атлас](http://127.0.0.1:8765/data), [FAQ](http://127.0.0.1:8765/data#curated).
Нийтийн багц: [v2](../data/content-draft-v2-20261015.json),
[эхийн нотолгоо](../data/content-evidence-v2-20261015.json),
[validator](../tools/validate_content_evidence.py), [client importer](client_tab_corpus.py).

```powershell
.\.venv\Scripts\python.exe tools/validate_content_evidence.py data/content-draft-v2-20261015.json data/content-evidence-v2-20261015.json --root . --require-sources
```

Strict шалгалтад private saved source файлууд хэрэгтэй. Шинэ clone portable hash/
dependency шалгалтыг хийнэ; private snapshot/DB байхгүй бол яг ижил201 corpus-г
баталсан гэж үзэхгүй. Локал файлууд:
`website/snapshots/nmct-supplement-20261014T165540Z/`,
`website/document-excerpts-supplement-20261015.json`,
`website/client-tab-excerpts-20261015.json`.
Нөөц/импортын нотолгоо `runtime/week04-coverage-import-20261015.json`,
`runtime/week04-content-import-20261015.json`.

Нэмэлт эх ба FAQ нь зөв хариултын баталгаа биш: шинэ24 AI probe8pass/6partial/
10fail. Одоо утгын холбоо, тооны үүрэг, хугацаа, шаардлагын хүрээ, хэт татгалзлыг
засах хэрэгтэй. [Бүх хэмжилтийн нэгтгэл](../docs/experiments/rag-integration-20261012.json).

---

## Өмнөх 2026.10.14 snapshot-ийн түүхэн тайлбар

# NMCT албан сайтын мэдээллийн сан — шинэчлэлт 2026.10.14

[Албан сайтаас](https://nmct.edu.mn/) 2026.10.10-нд хадгалсан эхүүдийг ашиглаж байна.
Шинэ crawl хийгээгүй; эх HTML, зургууд, PDF болон анхны хүснэгтүүд өөрчлөгдөөгүй.

| Хэмжээ | Дүн |
|---|---:|
| HTML хуудас | 72 |
| Анхны HTML chunk | 153 |
| Давхардал/хамрах хүрээг шүүсэн HTML хэсэг | 139 |
| Эх баримт | 1 PDF, 4 PNG |
| Баримтаас сонгож буулгасан хэсэг | 21 |
| RAG-д эрэмбэлэх нийт хэсэг | 160 |
| Анхны crawl-д 404 өгсөн холбоос | 2 |

Дөрвөн PNG болон PDF-ийн хоёр хуудсыг дүрсээр үзэж, 21 заалтыг AI туслах эхтэй нь
тулгасан. Автомат PDF текстэд үгийн дараалал/огнооны алдаа байсан тул тэр гаралтыг
шууд хариултын эх болгоогүй. Мөр шилжилт ба bullet-ийг хэвийнжүүлсэн **сонгосон
заалтын буулгалт**; бүтэн OCR, хүний gold, сургуулийн ажилтны баталгаа гэж нэрлэхгүй.

Журмын цээж зураг, мэргэжлийн нэмэлт сонголт, ярилцлага, гэрээ, эрх шилжүүлэх,
гадаадад боловсрол эзэмшсэн тохиолдол, олимпиадын ангилал/шагнал/хязгаарлалт нэмэгдсэн.
Эхийг URL + asset SHA256 + хувилбар + хуудас/заалтаар холбоно. Corpus анх унших/
шинэчлэх үед буруу hash, эвдэрсэн буулгалтыг хасна. Cache нь DB-ийн mtime/size/огноогоор
шинэчлэгддэг; asset файлыг DB өөрчлөхгүйгээр сольсон тохиолдлыг хүсэлт бүрт дахин
hash шалгахгүй. Frozen snapshot-ийг өөрчлөхгүй, засварт шинэ хувилбар хэрэглэнэ.
Нийтийн GitHub-д бүтэн frozen DB/21 буулгалтын bundle байхгүй; hash/код байгаагаар
өөр компьютер дээр яг ижил corpus-ийг бүрэн сэргээсэн гэж тооцохгүй.
Түүхэн `assets.extraction_status=binary_only` хэвээр; тусдаа `document_extractions`
хүснэгт нягталсан нэмэлтийг хадгалдаг. Анхны эхийг буцааж бичдэггүй.

Албан эхийг төсөлд ашиглах хэрэглэгчийн шийдвэр хүчинтэй. Дахин сургуулийн approval
шаардахгүй. Гэхдээ эхийн он/огноог хадгална; хуучин элсэлтийн хугацааг өнөөдөр
нээлттэй гэсэн мэдэгдэл болгохгүй. Сайтын banner/main-ийн зөрүү хэвээр бүртгэгдэнэ.
Client-side tab, бүх хүснэгт/заалт, гаднын болон нэвтрэх шаардлагатай хэсэг бүрэн
хамрагдаагүй. Номын сангийн зээлэх хугацаа, дотуур байрны төлбөрийн эх олдоогүй.

## Гол файлууд ба дахин шалгах

- `database/website.db`: эхийн түүх болон `document_extractions`.
- `website/snapshots/nmct-20261010T045245Z/`: анхны эх, manifest/hash.
- `website/document-excerpts-20261012.json`: локал 21 заалтын буулгалт, арга, locator.
- [document_corpus.py](document_corpus.py): hash/хувилбар шалгаж импортлох CLI.
- [Хөгжүүлэлтийн 36 асуулт](../data/rag-source-dev-20261012.json).
- [Нотолгооны нэгтгэл](../docs/experiments/rag-integration-20261012.json): `document_source_extension`.

Төслийн үндсэн хавтсаас:

```powershell
.\.venv-modeltools\Scripts\python.exe -m CORE.document_corpus CORE/website/document-excerpts-20261012.json
.\.venv-modeltools\Scripts\python.exe tools/evaluate_source_retrieval.py
.\.venv-modeltools\Scripts\python.exe tools/evaluate_source_retrieval.py --lexical-only --output runtime/source-lexical-check.json
```

Ижил импорт давхардахгүй. Шинэ clone-д raw snapshot/DB/буулгалт ирэхгүй; collector-оор
эхээ бүрдүүлж, `tests/test_document_corpus.py` дахь schema-гаар URL, version,
asset_sha256, title, method, reviewer_kind, coverage, passages(locator/text)-тай
багц бэлтгэнэ. Эхийн шинэ хувилбарыг дахин нягтална. Runtime код нь standard library;
энэ удаагийн PDF нягталгаанд pypdf 6.20.0, pypdfium2 5.14.0, Pillow 12.3.0 ашигласан.

Хайлтын дүн: баримт импортолсны дараа зорилтот хэсэг top5-д 25/30; үгийн хувилбар
ба anchor-ийн хамрах хүрээг тооцсоны дараа 30/30 болсон. Зарим асуултын ижил мэдээлэл
HTML-д бас бий; хэмжүүр нь **заасан URL ба текстийн хэсэг олдсон эсэх**, хариултын
ерөнхий үнэн зөв байдал биш. Эдгээр асуултаар тохируулга хийсэн, held-out багц биш.

## 2026.10.14 — хамрах хүрээний дахин аудит

Шинэ crawl/import хийгээгүй, DB ба frozen160 хэсгийн hash өөрчлөгдөөгүй.
6 тэнхимийн хадгалсан Next Flight-д goalsJson/achievementsJson байдаг; visible
main нь эхний tab-аар хязгаарлагдсан. Зарим утга placeholder, зарим статистик
огноогүй эсвэл өөр snapshot-ийн тоотой тул шууд merge хийгээгүй. SQL ур чадвар
байгаа ч долоо хоногийн хичээлийн цаг олдоогүй. Бүх сайтад огт байхгүй гэж дүгнэхгүй.
77 эхийн metadata/locator-ийг атласаас нягтална; 72 HTML-д source_updated_at
тодорхойгүй (мэдээний огноо body-д байж болно). 160indexed хэсгээс news listing
хэсгүүдийг production candidate болгохгүй. Дэлгэрэнгүй нь ROADMAP-PROGRESS-д.
