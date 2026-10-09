# THesisS

Сургуулийн албан эхэд тулгуурлан Монгол дуугаар мэдээлэл өгөх дипломын хөгжүүлэлтийн төсөл.

Зорилтот урсгал: **микрофон → STT → асуултын зам/хайлт → эхтэй хариулт → TTS**. 2026.12.15-ны хязгаарласан demo-г эцсийн roadmap-ийн дагуу бэлтгэнэ. Өөрийн STT/LLM сургах ажил одоогийн хүрээнд байхгүй.

## Ажиллаж буй хэсэг

- WAV бичлэг, CPU STT, WER/CER тооцоо, онлайн TTS-ийн тусдаа командууд.
- Эх/хувилбар, fact, FAQ-ийн схем ба баталгаа/огнооны шалгалт.
- SQLite импорт, давтан импортын хамгаалалт, эхтэй fact/FAQ preview.
- BM25 болон локал multilingual-e5-small-ийн хөгжүүлэлтийн харьцуулалт.
- 20 гол + 6 нэмэлт өгүүллийн бүртгэл, сонгосон аргын тэмдэглэл.

Агуулга одоогоор **draft**. SQLite preview нь ID-аар мэдээлэл харуулна; автомат router биш. Бүтэн voice/API/router/C-RAG урсгал хараахан дуусаагүй. [Бодит үр дүн, үлдсэн ажил](docs/PROGRESS.mn.md).

## Шууд ажиллуулах SQLite туршилт

Python 3.11 ашиглана. Доорх импорт/preview/test нь зөвхөн Python standard library шаарддаг. Repository-ийн үндсэн хавтсаас PowerShell-д:

```powershell
py -3.11 import_content.py import data/content-draft-v1.json --allow-draft
py -3.11 import_content.py status
py -3.11 import_content.py preview faq.contact --allow-draft --as-of 2026-10-10
py -3.11 -m unittest discover -s tests -v
```

Өгөгдлийн сан `runtime/content.db`-д үүснэ. Ижил JSON-г дахин импортлоход давхардахгүй. `--allow-draft` нь хөгжүүлэлтийн харах горим; эхийг баталсан гэсэн үг биш. Ердийн preview-д батлагдаагүй агуулгын answer хоосон, татгалзсан шалтгаан харагдана. [SQLite ажиллагаа](docs/CONTENT-STORE.mn.md).

## STT ба TTS орчин

Шинэ clone-д орчин байхгүй бол:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe check_environment.py
.\.venv\Scripts\python.exe record.py --list-devices
```

Өөрийн шинэ бичлэгийг шинэ нэрээр хадгална:

```powershell
.\.venv\Scripts\python.exe record.py --seconds 8 --output audio/my-question.wav
.\.venv\Scripts\python.exe stt.py audio/my-question.wav --output results/my-question-stt.json
.\.venv\Scripts\python.exe tts.py --text-file data/tts-text.txt --output results/my-tts.mp3
```

`stt.py` анхны `small` baseline; сонгосон Монгол checkpoint ашиглах нь [моделийн тусдаа зааварт](docs/MODEL-SETUP.mn.md) бий. TTS нь онлайн Edge үйлчилгээний community client-ийн туршилт; эцсийн үйлчилгээний сонголт хараахан биш. Өмнө хадгалсан файл дээр командууд дарж бичихгүй.

## Уншлага ба судалгаа

[Унших заавар](STUDENT-READING-GUIDE.mn.md) · [26 өгүүлэл](RESEARCH-26-PAPERS.mn.md) · [RQ/үнэлгээний ноорог](THESIS-RESEARCH-SYNTHESIS-2026-10-10.mn.md) · [Эцсийн roadmap](ROADMAP-FINAL-2026-10-07.mn.md)

26 өгүүллийг бүгдийг бүтнээр уншиж байж код эхлэх шаардлагагүй. Гол 20-ын асуудал/арга/үнэлгээ/хязгаар/төслийн шийдвэрийг тэмдэглэж, ашиглаж буй аргын эхийг гүн уншина. Зургаан нэмэлт эхийг хэрэгцээгээр сонгоно. Ассистентийн эхийн шалгалтыг суралцагчийн бүтэн уншлага гэж тооцохгүй.

## Repository-д багтсан өгөгдөл

Нийтэд нээлттэй сургуулийн эхээс бэлтгэсэн draft агуулга, хөгжүүлэлтийн асуулт, ассистентийн зохиосон хайлтын жишээ, судалгааны бүртгэл орсон. Хувийн дуу, хүний transcript, чатны хуулбар, сонсголын бүртгэл, моделийн жин, `.venv`, локал DB болон backup ороогүй. Моделийн source/revision/hash тохиргоо тусдаа; жинг нийтийн эхээс татна. Хамааралтай сан, моделийн лиценз нь өөрийн эхэд хэвээр.
