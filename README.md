# THesisS

Сургуулийн албан эхэд тулгуурлан Монгол дуугаар мэдээлэл өгөх дипломын хөгжүүлэлтийн төсөл.

**Төслийн нэг эхлэх төв: [CORE/README.mn.md](CORE/README.mn.md).**
`CORE/OPEN-PROJECT.cmd` нь бүх код, үндсэн ойлголт, тайлантай VS Code workspace нээнэ;
`CORE/DEMO.cmd` нь demo-г нээнэ. [Roadmap-ийн бодит явц](CORE/ROADMAP-PROGRESS.mn.md).

Албан `nmct.edu.mn` сайтаас **72 нээлттэй HTML хуудас, 153 текстийн хэсэг,
нэг PDF/дөрвөн журмын зураг** локал SQLite эхийн санд хадгалсан.
Demo-ийн «Албан сайтаас татсан мэдээлэл» хэсэгт эхийн текстээр хайна.
Энэ нь сургуулиар баталгаажсан хариулт биш; PDF/зураг доторх текстийн боловсруулалт үлдсэн.
[Цуглуулалтын хамрах хүрээ, хадгалалт, дахин ажиллуулах заавар](CORE/WEBSITE-DATA.mn.md).

**Одоо үзэж болох үр дүн:** demo дээр асуултын замыг шалгаж,
бүртгэлтэй exact асуултад эхтэй ноорог хариулт, он дутуу үед тодруулга,
эх/баталгаа дутуу үед тайлбартай татгалзал үзнэ. Мөн SQLite BM25 FAQ/веб эхийн
хайлт, хэрэглэгч зөвшөөрсөн q01–q03 дууны өмнөх STT жишээ ажиллана.
[3-р долоо хоногийн сонголт ба бодит хугацаа](CORE/WEEK03-DECISIONS.mn.md).

Зорилтот бүтэн урсгал: **микрофон → STT → асуултын зам/хайлт → эхтэй хариулт → TTS**. 2026.12.15-ны хязгаарласан demo-г эцсийн roadmap-ийн дагуу бэлтгэнэ. Өөрийн STT/LLM сургах ажил одоогийн хүрээнд байхгүй.

## Demo-г нээх

Windows дээр төслийн үндсэн хавтасны **DEMO.cmd** дээр хоёр дарна.
Эхлүүлэгч серверийг шалгаж, хэрэгтэй үед асаагаад браузерыг нээнэ.
Шинэ clone-д draft DB-г нэг удаа импортлоно. Python 3.11+ хэрэгтэй;
байгаа `.venv`-ийг түрүүлж ашиглана.

Тайлангууд **reports/** хавтаст төвлөрсөн. [Одоогийн ахиц](reports/current/PROGRESS.mn.md),
[унших заавар](reports/research/STUDENT-READING-GUIDE.mn.md),
[demo-ийн тайлбар](reports/system/SQLITE-SEARCH.mn.md)-аас эхэлнэ.

## Терминалаас ажиллуулах

Python 3.11 ашиглана. Одоогийн төсөлд `runtime/content.db` байгаа бол үндсэн хавтсаас:

```powershell
python demo_server.py
```

**http://127.0.0.1:8765** нээнэ. `Ctrl+C` серверийг зогсооно. Шинэ clone-д DB үүсгэх эхний алхам:

```powershell
py -3.11 import_content.py import data/content-draft-v1.json --allow-draft
py -3.11 demo_server.py
```

Demo, SQLite, BM25-д Python standard library хангалттай; модель татах шаардлагагүй. Агуулга **зургаан эх, 10 fact, таван FAQ бүхий draft**. «Холбоо барих утас хэд вэ?» гэж хайгаад draft горимыг илэрхий сонгож, candidate-ийн ноорог хариултыг үзэж болно. Ердийн горим батлагдаагүй хариултыг хаана. Ойролцоо FAQ олдох нь асуултад зөв хариулж чадсаны баталгаа биш. [Дэлгэрэнгүй demo/хайлтын заавар](reports/system/SQLITE-SEARCH.mn.md).

## Ажиллаж буй хэсэг ба үр дүн

- WAV бичлэг, CPU STT, WER/CER тооцоо, онлайн TTS-ийн тусдаа командууд.
- SQLite-ийн давхардахгүй импорт, багц/эхийн хувилбар, баталгаа/огнооны шалгалт.
- SQLite-д суурилсан амьд BM25 хайлт, зөвхөн унших браузерын demo, эхтэй FAQ preview.
- Дүрэмтэй A/B/D/E чиглүүлэлтийн суурь: exact/alias, он/нэр, баталгаа/хугацаа; fuzzy-гээс хариулт үүсгэхгүй, C нээгдээгүй.
- Локал multilingual-e5-small-ийн өмнөх хөгжүүлэлтийн харьцуулалт: таван FAQ, 15 proposed асуултад BM25 top1 **10/15**, E5 **14/15**; хүний баталсан gold биш.
- STT-ийн өмнөх 13 батлагдсан reference дээр **WER 36.0%, CER 16.9%**; таних accuracy биш.
- 20 гол + 6 нэмэлт өгүүллийн бүртгэл, сонгосон аргын тэмдэглэл.

Микрофон, шинэ STT, хариултын TTS энэ хуудсанд холбогдоогүй. Бүтэн A/B/C/D/E router, C-RAG болон эцсийн чанарын хүлээн авалт дуусаагүй. [Бодит үр дүн, үлдсэн ажил](reports/current/PROGRESS.mn.md).

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

BM25/E5 арга ба хязгаарлалтыг [хайлтын тэмдэглэл](papers/05-retrieval-method-notes.mn.md), эшлэл/хариултын үнэлгээ ба UI-ийн шийдвэрийг [ALCE/RAGAs/Human–AI тэмдэглэл](papers/06-evaluation-interface-method-notes.mn.md)-тэй холбосон. Энэ demo дээр шинэ training, LLM эсвэл автомат judge ажиллуулаагүй.

## Repository-д багтсан өгөгдөл

Нийтэд нээлттэй сургуулийн эхээс бэлтгэсэн draft агуулга, хөгжүүлэлтийн асуулт, ассистентийн хайлтын жишээ, судалгааны бүртгэл орсон. **Хэрэглэгч нийтлэхийг илэрхий зөвшөөрсөн гурван WAV (q01–q03)** ба тэдгээрийн батлагдсан текст/өмнөх STT гаралт [demo/audio/samples.json](demo/audio/samples.json)-д тайлбарлагдсан. Эдгээр нь дууны туршилтын жишээ; сургуулийн fact эсвэл төгс STT-ийн баталгаа биш. Дууг дахин ашиглах нэмэлт лиценз олгоогүй.

Бусад хувийн дуу/transcript, чатны хуулбар, сонсголын бүртгэл, `.venv`, локал DB болон backup ороогүй. Том моделийн жин үндсэн Git history-д орохгүй; release болон нийтийн эхээс тусад нь авна. Хамааралтай сан, моделийн лиценз нь өөрийн эхэд хэвээр.
