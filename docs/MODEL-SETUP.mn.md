# Бэлэн моделийг тусдаа татах заавар

Моделийн жин Git repository-д байхгүй. Доорхыг шинэ clone-д хэрэгтэй үед хийнэ. Одоогийн ажлын компьютерт модель, орчин аль хэдийн байгаа бол дахин суулгаж/татах шаардлагагүй.

## CPU хэрэгслийн орчин

Windows, Python 3.11 дээр:

```powershell
py -3.11 -m venv .venv-modeltools
.\.venv-modeltools\Scripts\python.exe -m pip install -r requirements-modeltools.txt
.\.venv-modeltools\Scripts\python.exe -m pip check
```

Туршсан torch 2.8.0 CPU wheel-ийн албан index-ийг requirements файлд заасан. [PyTorch-ийн өмнөх хувилбарын суулгалтын заавар](https://pytorch.org/get-started/previous-versions/). Энэ нь GPU тохируулсан гэсэн үг биш.

## E5 small хайлт

```powershell
.\.venv-modeltools\Scripts\python.exe tools/download_embedding_checkpoint.py
.\.venv-modeltools\Scripts\python.exe retrieval_probe.py --allow-draft --output-dir results/retrieval-new-run
```

Default нь intfloat/multilingual-e5-small. Public config/model-catalog дахь source/revision, safetensors SHA256-г ашиглана. Metadata нь model card/жин биш; download нь жин болон шаардлагатай root assets-ийг авч hash шалгана. --allow-draft нь сургуулийн агуулгыг зөвшөөрсөн гэж батлахгүй. Давтан туршилтад шинэ output-dir өгнө.

## Cafet Монгол STT

```powershell
.\.venv-modeltools\Scripts\python.exe tools/download_public_checkpoint.py
.\.venv-modeltools\Scripts\python.exe tools/convert_mn_checkpoint.py
.\.venv\Scripts\python.exe stt_mn.py audio/my-question.wav
```

Эх Cafet/whisper-small-mongolian checkpoint-ийг pinned revision-аас татаж, CTranslate2 format руу локал хөрвүүлнэ. Хөрвүүлэлт нь training/fine-tuning биш. stt_mn.py нь тестэлсэн converted hash ба decoder тохиргоог шалгана. Өөр runtime-ийн хөрвүүлэлт өөр hash гаргавал тэр жинг тестэлсэн жинтэй ижил гэж дүгнэхгүй; хүлээлттэй hash-г дур мэдэн өөрчлөхгүй.

Local private data/stt-model-choice.json байгаа бол түүнийг ашиглана; шинэ clone-д минимал config/stt-development.json fallback байна. Тэнд хувийн transcript эсвэл нэг бүрийн оноо байхгүй.

[Cafet эх](https://huggingface.co/Cafet/whisper-small-mongolian) · [E5 эх](https://huggingface.co/intfloat/multilingual-e5-small). Лиценз, шаардлагыг эх тус бүрээс харна. Downloader нь model output-г models дотор хязгаарлаж, ажиллаж буй таталтыг lock-оор тусгаарлана. Existing жинг дарж conversion хийхгүй.
