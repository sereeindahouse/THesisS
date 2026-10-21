<!-- independent-audit-public-20261021:start -->
## 2026.10.21 — Аудитын шинэ дүгнэлт

897 автомат тестийг бие даан дахин ажиллуулахад тэнцсэн; 20 live асуултыг шалгахад сургуулийн түүхийн асуултыг буруу мэдээгээр хариулсан алдаа хэвээр байна. Нэг synthetic STT→хариулт→TTS урсгал ажилласан нь хүний чанарын оноо биш. Ижил8 хөгжүүлэлтийн AI дүн Gemma8/8=best3; ерөнхий LLM/STT/TTS сайжрал батлагдаагүй. Өгүүлбэрийн boundary, completeness хүсэлтийн scope, тасарсан хэсгийн context холбоонд гурван давтагдах доголдол бүртгэв. [Бодит явц, хязгаар](CORE/ROADMAP-PROGRESS.mn.md).

<!-- independent-audit-public-20261021:end -->

<!-- core-next-public-20261021:start -->
## 2026-10-21 source checkpoint

Current local verification: **897 tests passed**. Source selection preserves paired direction/name cards and same-company course delivery context. On the same8 observed-development questions, AI completeness is8/8 for Gemma and8/8 for the non-LLM best3 condition; relevance/repetition errors remain. These are not held-out human accuracy results.

Raw Cafet STT remains WER36.02% on13 speaker-confirmed development utterances. A conservative offline four-ASR fusion trial kept67 word errors and reduced184 character errors to183; it was not promoted. No training/new model download. [Readable system explanation](CORE/CONCEPTS.mn.md).

Private recordings, transcripts, runtime results, databases, teacher-photo assets and models remain local. Only the previously authorized q01–q03 demo samples are included. A public source checkout needs the documented model/data setup; this checkpoint is not a full clean-machine deployment.
<!-- core-next-public-20261021:end -->

<!-- delivery-navigation-20261021:start -->
## 2026.10.21 — Ажиллаж буй demo, мэдээлэл шинэчлэх хэсэг

[Чат](http://127.0.0.1:8765/) · [Admin](http://127.0.0.1:8765/admin) · [Явц](http://127.0.0.1:8765/data#progress).
[CORE/ADMIN.cmd](CORE/ADMIN.cmd) админыг нэг даралтаар нээнэ.
[Засах/нийтлэх/буцаах заавар](CORE/ADMIN-GUIDE.mn.md).
Staging/publish/rollback, STT raw/edited холбоос, TTS он/утасны хэлбэржилт хэрэгжсэн;
787 локал тест,23бодит releaseHTTP тэнцсэн. RawSTT WER36.02% хэвээр.
Байнгын hosting, хүний хараат бус чанарын дүн хэмжсэн гэж тайлагнаагүй.
<!-- delivery-navigation-20261021:end -->

<!-- core-finalization-20261017:start -->
## 2026.10.17 — Үндсэн урсгалын үргэлжлэл

705 локал тест тэнцсэн. Стандарт нийтийн HTTPS-ийн27HTTP шалгалт, хэрэглэгчийн
6TTS сонсголын үнэлгээ бүртгэгдсэн. Шинэ24 анхны AI17/7; засварын дараа24corepass,
9presentation partial. Өмнөх24corepass/50facts50pass. Бүгд development; human gold биш.
RawSTT WER36.02% хэвээр. [Дэлгэрэнгүй явц](CORE/ROADMAP-PROGRESS.mn.md).
Браузерт сертификат суулгах шаардлагагүй; сервер ажиллаж байхад түр HTTPS ашиглана.
<!-- core-finalization-20261017:end -->

## 2026.10.17 — RAG, STT, TTS

651локал тест PASS; хувийн өгөгдөлгүй export650PASS/1SKIP.
Шинэ24 одоо observed development: AI core24pass/50facts50pass,4presentation partial;
хүний accuracy биш. STT rawWER36.02% хэвээр; шинэ initial_prompt51.08%муудсан тул
нэвтрүүлээгүй, recording/decoder review сануулга нэмсэн. TTS6first+6cachehit/12decode;
давтан дуу0.055–0.111s (энэ6жишээ), хүний сонсгол хэмжээгүй. Gemma нь C-д эхийн
ID сонгож, сервер үгчлэн харуулна; WhisperSTT, EdgeTTS тусдаа.
[Явц ба хязгаар](CORE/ROADMAP-PROGRESS.mn.md) · [Урсгалын ойлголт](CORE/CONCEPTS.mn.md).
Нийтийн HTTPS, бодит төхөөрөмж/хүний study, эцсийн дипломын хяналт үлдсэн.

---

# THesisS

## 2026.10.16 — Whisper-ийн одоогийн сайжруулалт

Cafet/Whisper-small хэвээр. Ижил13development бичлэгт baselineWER36.02/CER16.90%;
hotwords47.31/23.05%муудсан,beam10ижил тул нэвтрүүлээгүй. Шинэ яриа байгаа эсэхийн
локал gate нь аудиог тайрахгүй:17/17speech нэвтэрч,2/2nonspeech хориглогдсон;
нэмэлт8богино/сулsynthetic speech нэвтэрсэн. Энэ нь WER сайжирсан гэсэн дүн биш.
590локал тест PASS; loadedSTThash/fingerprint-ийг collector шалгана.
Багшийн scope:тохиргоо/системийн сайжруулалт+харьцуулалт; өөрийн training/download0.
Дэлгэрэнгүй: [явц](CORE/ROADMAP-PROGRESS.mn.md). Доорх нь өмнөх checkpoint-ийн түүх.

---

## 2026.10.15 — тасарсан таван алхмын үргэлжлэл, эцсийн локал V6

**568 автомат тест PASS; серверийн10 loaded hash диск/freeze-тэй таарсан.**
Observed development AI review: **24 =21 зөв/3 дутуу/0 алдаатай;16 =16 overall pass**.
16-ийн required facts **40 pass/2 partial/2 fail** тул16/16-г100% accuracy гэж нэрлэхгүй.
Reviewer засварт оролцсон; human_review=null. Хоёр багц хоёулаа development.

Ижил4 синтетик WAV-аар STT→typed/raw RAG→хариултын TTS/decode **4/4**;
typed smoke4/4, raw анхны шалгуур2/4. Koha→«ков/коо» үед автоматаар сольж
хариулахгүй, D тодруулга өгсөн. Хоёр corrected бүтэн query-г илэрхий сонгосныг
дуурайлган шалгахад2/2 номын тоо/он гарсан; хүний туршилт биш.

Таван алхмаас1/2/3/5 дууссан;4-ийн аудио дууссан, шинэ browser visual/playback
шалгалт URL-ийг итгэлтэй тогтоож чадаагүй Computer Use хоригт үлдсэн.
Бүх5-ыг бүрэн дууссан гэж үзэхгүй. Чанарын үлдэгдэл, түүхий нотолгоо ба дараагийн
ажил: [явцын үндсэн бүртгэл](CORE/ROADMAP-PROGRESS.mn.md).
Week3 engineering6/6, operational checklist5/8 хэвээр; дипломын хувь биш.
Шинэ модель таталт/өөрийн training/commit/push хийгээгүй; анхны roadmap хэвээр.
Доорх хуучин тоо/untuned тэмдэглэлүүд нь тухайн checkpoint-ийн түүх.

---

## Week4: эхийн өргөтгөл ба шинэ асуултын үнэлгээ — 2026.10.15

**75 HTML + 5 баримт; 201 хайлтын хэсэг (150 HTML + 21 баримт + 30 нэмэлт таб).**
Чанар, түүх, сургалтын орчны 3 хуудсыг нэмж, 6 тэнхимийг дахин татсан.
Хоосон загвар ба огноогүй табын тоон үзүүлэлтийг хассан. Бүх сайт/таб хамрагдаагүй.
Үндсэн HTML болон нэмэлт табын татсан огноо/hash тусдаа; хуучин эхийг шинэ мэт
огноолохгүй. Хоёр SQLite-г нөөцөлж, хуучин run/package-г хадгалсан; импорт давхардахгүй.

**40 fact / 30 FAQ / 14 эхийн хувилбарын бүртгэл (11 өөр URL).** Шинэ 30 fact,
25 FAQ-ийн эх/заалт/он/хүрээг шалгасан; 39 exact асуулт/alias бодит HTTP-ээр B,
LLM0. GitHub-ийн шинэ clone v2 багцыг ашиглана; private бүтэн corpus автоматаар ирэхгүй.
[Эхийн атлас](http://127.0.0.1:8765/data) · [FAQ](http://127.0.0.1:8765/data#curated).

**Засварт ашиглаагүй 24 шинэ асуултын анхны AI үнэлгээ: 8 pass / 6 partial / 10 fail.**
Асуулт, зөв эх, шаардсан баримт, rubric-г гаралтаас өмнө царцаасан. Хүний gold,
ерөнхий accuracy биш. 14 хариулттай кейсийн 13-д шаардсан эх олдсон боловч
«тус бүрээс3/нийт15»-ыг «тус бүрээс15» болгох, төлөвлөснийг гүйцэтгэсэн мэт
хэлэх, N2 шаардлагыг өөр замд ерөнхийлөх алдаа гарсан. Эх олдох ба зөв хариулах
хоёр тусдаа. Дараагийн засварт энэ24-ийг ашиглавал development багц болно.

432 локал тест51.999s, 9 шинэ browser шалгалт; 375px mobile хэвтээ overflowгүй.
24HTTP амжилттай:15C/8E/1D,20LLMcall; warm бичгэн HTTP медиан2.741s.
STT/TTS, cold-start, төхөөрөмжийн хугацааг энэ хэмжилт оруулаагүй.
Raw: `runtime/week04-untuned-live-20261015.json`; dimensional AI review:
`runtime/week04-untuned-reviewed-20261015.json`.

Week3 техникийн6/6 хэвээр. Week4-ийн хязгаарласан эх/facts/FAQ ба AI хэмжилт бэлэн;
утгын алдааны засвар, хүний final QA, бодит typed/raw/edited-STT, HTTPS/таблет үлдсэн.
Ажиллах хувилбарын checklist5/8 хэвээр; нийт дипломын хувь биш.
Анхны roadmap өөрчлөгдөөгүй; шинэ модель сургалт/таталт хийгээгүй.


**2026.10.14 — week4-ийн 40 асуулт, автомат дууны туршилт ба алдааны засвар.**
[Эхийн атлас](http://127.0.0.1:8765/data) · [Явц](http://127.0.0.1:8765/data#progress).
40 reference-г гаралтыг үзэхээс өмнө тогтоосон: 26 хариулагдах / 6 тодруулах /
8 тухайн frozen багцад батлагдаагүй. 12 нь өмнөх атрибутын шинэ найруулга.
Энэ нь туслахын development багц; хүний gold/final held-out үнэлгээ биш.

Бичгийн100/ярилцлагын20, гадаад ЕБС-ийн хоёр баримт, бүртгэлийн хураамж/
суралцах гэрээ, жил/сар, эхгүй фонт/SQL цагийн андууралтыг bounded дүрмээр зассан.
Эцсийн 40 хүсэлт **23A / 3C / 6D / 8E**. Туслахын оношлогоо **39 pass / 1 partial**
(C ажлын нэрсийн найруулга); бүх human_review null. Засварт ашигласан тул энэ
дүнг системийн нийт зөв хариултын хувь гэж тооцохгүй.

**6 асуулт × Батаа/Есүй = 12 синтетик бичлэг**: асуултын TTS → WAV → Cafet STT →
typed/raw RAG → хариултын TTS/decode. Өмнөх ба дараах яг ижил WAV, raw STT;
синтетик **WER27.8%, CER7.3%** өөрчлөгдөөгүй. SQL нэр алдагдахад цагийн оронд
хөтөлбөрийн тайлбар өгөх алдааг хаасан; эргэлзээтэй үгийг тодруулна. ASR-ийг
дахин сургаагүй, хүний ярианы шинэ benchmark биш.
[SELF-CHECK.cmd](CORE/SELF-CHECK.cmd) хоёр дарвал шинэ private хавтсанд туршилт хийж,
дуу/текст/хариултын HTML-г нээнэ. Онлайн Edge TTS ашиглана; хэдэн минут үргэлжилнэ.
Одоогийн харагдац: `runtime/voice-selftest-after-20261014/index.html`.

**347 автомат тест, хувийн viewer-ийн 7 браузерийн шалгалт тэнцсэн.**
Импортолсон кодын hash-ийг collection-оос өмнө шалгана; хуучин кодтой серверийг
бодитоор блоклосон. Өмнөх буруу/бүтэлгүй логийг дарж бичээгүй.
Week3 техникийн6/6 дууссан. Week4-ийн эхийн бүрэн хамрах хүрээ, facts/FAQ
өргөтгөл, хүний хараат бус QA үлдсэн. Ажиллах хувилбарын checklist хэвээр
**5 бэлэн / 2 үргэлжилж буй / 1 үлдсэн**; нийт дипломын хувь биш.
[Бодит нотолгооны нэгтгэл](docs/experiments/rag-integration-20261012.json).


Сургуулийн албан эхэд тулгуурлан Монгол дуугаар мэдээлэл өгөх дипломын хөгжүүлэлтийн төсөл.

**Төслийн нэг эхлэх төв: [CORE/README.mn.md](CORE/README.mn.md).**
`CORE/OPEN-PROJECT.cmd` нь бүх код, үндсэн ойлголт, тайлантай VS Code workspace нээнэ;
`CORE/DEMO.cmd` нь demo-г нээнэ. [Roadmap-ийн бодит явц](CORE/ROADMAP-PROGRESS.mn.md).

Албан `nmct.edu.mn` сайтаас **72 нээлттэй HTML хуудас, 153 текстийн хэсэг,
нэг PDF/дөрвөн журмын зураг** локал SQLite эхийн санд хадгалсан.
Demo-ийн «Албан сайтаас татсан мэдээлэл» хэсэгт эхийн текстээр хайна.
Албан сайтад нийтэлсэн эхийг хэрэглэгчийн шийдвэрээр ашиглана; PDF/зурагт 21 сонгосон хэсэг нэмэгдсэн; бүтэн боловсруулалт ба client tab үлдсэн.
[Цуглуулалтын хамрах хүрээ, хадгалалт, дахин ажиллуулах заавар](CORE/WEBSITE-DATA.mn.md).

**Одоо ажиллаж буй урсгал:** микрофон эсвэл аудио файл → локал Cafet STT →
таньсан текстээ засах → A/B/C/D/E зам ба эхийн шалгалт → хариултын TTS → сонсох.
Бүртгэлтэй асуултад албан эхийн хариулт, он дутуу үед тодруулга,
эх/он/хамрах хүрээ дутуу үед тайлбартай татгалзал гарна. SQLite BM25 FAQ/веб эхийн хайлт,
q01–q03 дууны өмнөх жишээ мөн байна. Хуучин сонсголын хэрэгсэл заавал биш архивын
нэмэлт хэсэгт үлдсэн. [Модель ба үйлчилгээний сонголт](CORE/WEEK03-DECISIONS.mn.md).

2026.11.10-ны ажиллах хувилбарт хүрэх шинэ төлөвлөгөөг CORE-ийн явцын файлд мөрдөнө.
Бүх хэллэгийн чиглүүлэлт, эхийн сангийн өргөтгөл, бодит төхөөрөмж/орчны шалгалт үлдсэн.
Өөрийн STT/LLM сургаагүй; бэлэн модель ашигласан систем ба хэмжилт хөгжүүлж байна.

## Demo-г нээх

Windows дээр төслийн үндсэн хавтасны **DEMO.cmd** дээр хоёр дарна.
Эхлүүлэгч серверийг шалгаж, хэрэгтэй үед асаагаад браузерыг нээнэ.
Шинэ clone-д draft DB-г нэг удаа импортлоно. Python 3.11+ хэрэгтэй;
байгаа `.venv`-ийг түрүүлж ашиглана.

Тайлангууд **reports/** хавтаст төвлөрсөн. [Одоогийн ахиц](reports/current/PROGRESS.mn.md),
[унших заавар](reports/research/STUDENT-READING-GUIDE.mn.md),
[demo-ийн тайлбар](reports/system/SQLITE-SEARCH.mn.md)-аас эхэлнэ.

## Чатаар асуух

1. Доорх бичих хэсэгт асуултаа бичээд **Enter** эсвэл **↑** дарна.
   Асуулт, хариулт ярианд үлдэнэ; **Shift+Enter** шинэ мөр нэмнэ.
2. **Микрофон** товчоор ярьж **«Дуусгах»** дарна; эсвэл **хавчаар** товчоор
   аудио файл сонгоно. Текст автоматаар гарна; нягтлаад илгээнэ.
3. Хариултын **«Эх сурвалж»** холбоосоор эх/огноог үзэж, **«Сонсох»** дарж
   дуут хариулт авна. Браузер тоглуулахгүй бол **▶** дарна.
4. Дээд **тохиргооны** товчоор хоолой, эхийн хайлт, FAQ/жишээ/техникийн
   хэрэгслийг нээнэ. LLM бэлэн үед л текстийн нэмэлт саналын товч харагдана.

Нэмэлт transcript/TTS үнэлгээ хийх шаардлагагүй. Ярианы түүх tab-д хадгалагдана;
эхтэй генератив RAG холбогдсон. Өмнөх яриаг автоматаар ойлгох олон ээлжийн
context memory хараахан байхгүй. Whisper/Cafet жинг шинээр сургаагүй.

**«Шинэ чат»** нь энэ хуудасны шинэ түр аудио/үр дүнг цэвэрлэж,
микрофон/дуу тоглуулахыг зогсооно. Эхний WAV болон хадгалсан хүний үнэлгээ хэвээр.
[Дэлгэрэнгүй demo заавар](reports/system/SQLITE-SEARCH.mn.md).

## Терминалаас ажиллуулах

Python 3.11 ашиглана. Одоогийн төсөлд `runtime/content.db` байгаа бол үндсэн хавтсаас:

```powershell
python demo_server.py
```

**http://127.0.0.1:8765** нээнэ. `Ctrl+C` серверийг зогсооно. Шинэ clone-д DB үүсгэх эхний алхам:

```powershell
py -3.11 import_content.py import data/content-draft-v2-20261015.json --allow-draft
py -3.11 demo_server.py
```

Бичгэн demo, SQLite, BM25-д Python standard library хангалттай. Дууны урсгалд `requirements.txt`-ийн сангууд ба локал Cafet жин хэрэгтэй; байгаа жинг дахин татахгүй. Шинэ clone-ийн v2 багц **14 эхийн хувилбар, 40 fact, 30 FAQ бүхий draft**. Launcher мөн v2-г сонгоно. «Холбоо барих утас хэд вэ?» гэж хайгаад draft горимыг илэрхий сонгож, candidate-ийн ноорог хариултыг үзэж болно. Ердийн горим хэрэглэгчийн зөвшөөрсөн албан эхийн бодлогыг мөрдөнө;
хуучин draft metadata нь сургуулийн ажилтны баталгаа биш. Ойролцоо FAQ олдох нь асуултад зөв хариулж чадсаны баталгаа биш. [Дэлгэрэнгүй demo/хайлтын заавар](reports/system/SQLITE-SEARCH.mn.md).

## Ажиллаж буй хэсэг ба үр дүн

- Браузерын микрофон/файл → локал CPU STT → текст засах → чиглүүлэгч → онлайн TTS урсгал; үе шатны хугацаа ба дуу тоглуулах удирдлага.
- Зургаан STT/гурван TTS-ийн хүний сонсголыг нэг дэлгэцээс хадгалах, backup/журнал, байгаа STT гаралтыг шинэ reference-ээр дахин оноох локал хэрэгсэл.
- WAV бичлэг, STT, WER/CER, TTS-ийн тусдаа командууд мөн хэвээр.
- SQLite-ийн давхардахгүй импорт, багц/эхийн хувилбар, баталгаа/огнооны шалгалт.
- SQLite-д суурилсан амьд BM25 хайлт, эхийн санг зөвхөн унших FAQ preview; хүний сонсголын бүртгэл тусдаа локал файлд хадгалагдана.
- A/B/D/E суурь дээр BM25 + E5 хайлт, эхтэй Gemma 3 4B C генераци ажиллана. Эшлэл байгаа нь утгын зөв байдлын баталгаа биш.
- Локал multilingual-e5-small-ийн өмнөх хөгжүүлэлтийн харьцуулалт: таван FAQ, 15 proposed асуултад BM25 top1 **10/15**, E5 **14/15**; хүний баталсан gold биш.
- STT-ийн өмнөх 13 батлагдсан reference дээр **WER 36.0%, CER 16.9%**; таних accuracy биш.
- 20 гол + 6 нэмэлт өгүүллийн бүртгэл, сонгосон аргын тэмдэглэл.

Дуу ба C-RAG холбогдсон. Хараат бус хариултын үнэлгээ, эхийн бүрэн хамрах хүрээ, latency тогтворжилт, таблет/HTTPS болон эцсийн чанарын шалгалт үлдсэн. [Бодит үр дүн, үлдсэн ажил](reports/current/PROGRESS.mn.md).

## CLI ба шалгалт

```powershell
py -3.11 import_content.py status
py -3.11 sqlite_retrieval.py "Холбоо барих утас хэд вэ?" --allow-draft
py -3.11 -m unittest discover -s tests -v
```

`--allow-draft` нь эхийг баталсан гэсэн үг биш. CLI-д хадгалсан асуулт/alias яг таарсан, бүрэн хариулт ба guard хангагдсан үед л хязгаарласан preview гарна; fuzzy matching үргэлж ranking төдий. [SQLite хадгалалтын заавар](reports/system/CONTENT-STORE.mn.md).

## STT, TTS ба моделийн жин

Шинэ clone-д дууны командын орчин хэрэгтэй бол:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe check_environment.py
```

Өөрийн шинэ бичлэгийг шинэ нэрээр хадгална:

```powershell
.\.venv\Scripts\python.exe record.py --seconds 8 --output audio/my-question.wav
.\.venv\Scripts\python.exe stt.py audio/my-question.wav --output results/my-question-stt.json
.\.venv\Scripts\python.exe tts.py --text-file data/tts-text.txt --output results/my-tts.mp3
```

`stt.py` нь анхны `small` baseline; сонгосон Монгол checkpoint ашиглах заавар [MODEL-SETUP.mn.md](reports/system/MODEL-SETUP.mn.md)-д бий. Туршсан Cafet STT ба E5 жинг [GitHub Release](https://github.com/sereeindahouse/THesisS/releases/tag/models-20261010)-д нийтэлсэн; серверийн хэмжээ/SHA256 нь локал архивтай таарсан. Шинэ clone-д `python tools/install_release_models.py all` нь архив/жин шалгаад суулгана; орчны шаардлага, pinned эхээс татах хувилбар нь моделийн зааварт бий. Одоогийн локал жинг дахин татах шаардлагагүй.

TTS нь онлайн Edge үйлчилгээний community client-ийн туршилт; эцсийн үйлчилгээний сонголт хараахан биш. Өмнө хадгалсан файл дээр дууны командууд дарж бичихгүй.

## Уншлага ба судалгаа

[Унших заавар](reports/research/STUDENT-READING-GUIDE.mn.md) · [26 өгүүлэл](reports/research/RESEARCH-26-PAPERS.mn.md) · [RQ/үнэлгээний ноорог](reports/research/THESIS-RESEARCH-SYNTHESIS-2026-10-10.mn.md) · [Эцсийн roadmap](ROADMAP-FINAL-2026-10-07.mn.md)

26 өгүүллийг бүгдийг бүтнээр уншиж байж код эхлэх шаардлагагүй. Гол 20-ын асуудал/арга/үнэлгээ/хязгаар/төслийн шийдвэрийг тэмдэглэж, ашиглаж буй аргын эхийг гүн уншина. Зургаан нэмэлт эхийг хэрэгцээгээр сонгоно. Ассистентийн эхийн шалгалтыг суралцагчийн бүтэн уншлага гэж тооцохгүй.

BM25/E5 арга ба хязгаарлалтыг [хайлтын тэмдэглэл](papers/05-retrieval-method-notes.mn.md), эшлэл/хариултын үнэлгээ ба UI-ийн шийдвэрийг [ALCE/RAGAs/Human–AI тэмдэглэл](papers/06-evaluation-interface-method-notes.mn.md)-тэй холбосон. Demo-ийн C замд локал Gemma бодитоор эхийн хэсэг сонгодог. Өөрийн модель сургаагүй; AI оношлогоог хүний gold үнэлгээ гэж тооцохгүй.

## Repository-д багтсан өгөгдөл

Нийтэд нээлттэй сургуулийн эхээс бэлтгэсэн draft агуулга, хөгжүүлэлтийн асуулт, ассистентийн хайлтын жишээ, судалгааны бүртгэл орсон. **Хэрэглэгч нийтлэхийг илэрхий зөвшөөрсөн гурван WAV (q01–q03)** ба тэдгээрийн батлагдсан текст/өмнөх STT гаралт [demo/audio/samples.json](demo/audio/samples.json)-д тайлбарлагдсан. Эдгээр нь дууны туршилтын жишээ; сургуулийн fact эсвэл төгс STT-ийн баталгаа биш. Дууг дахин ашиглах нэмэлт лиценз олгоогүй.

Бусад хувийн дуу/transcript, чатны хуулбар, сонсголын бүртгэл, `.venv`, локал DB болон backup ороогүй. Том моделийн жин үндсэн Git history-д орохгүй; release болон нийтийн эхээс тусад нь авна. Хамааралтай сан, моделийн лиценз нь өөрийн эхэд хэвээр.

Автомат дууны self-check нь төслийн локал Cafet модель/сан болон эхийн DB-тэй орчин шаарддаг. Шинэ clone нь private corpus/model-ийг өөрөө агуулдаггүй; setup заавар CORE төвд бий.
