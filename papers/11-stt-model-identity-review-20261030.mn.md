# Монгол ярианы танилт: хэрэглэгчийн харуулсан модель ба манай сонголтын аудит

**2026.10.30 — гол засвар:** хэрэглэгчийн шинэ screenshot дээр модель нь
`gemini-3.5-live-translate-preview` гэж шууд харагдсан. Сонирхож буй үр дүн нь
**Input transcript дахь Монгол текст**. Англи орчуулгын чанараар үүнийг
тайлбарлах шаардлагагүй. Өмнө хэрэгжүүлж, харьцуулсан
`gemini-3.5-transcribe` нь өөр model ID. Тэр үр дүнг Live Translate-ийн
оролтын танилтын үр дүн мэт хэрэглэх нь буруу.

## Албан эхээр баталсан зүйл

| Зүйл | Баталсан эх, уншсан хүрээ | Манай шийдвэр |
|---|---|---|
| Live Translate Монгол оролтын transcript өгдөг | [Google Live Translation](https://ai.google.dev/gemini-api/docs/live-api/live-translate): Get started, Sending audio, Configuration, Supported languages. `inputAudioTranscription` → `serverContent.inputTranscription.text`; Монгол `mn` жагсаалтад байна. | Энэ талбарын Монгол текстийг STT гаралт болгон авч RAG-д оруулж болно. Англи `outputTranscription`-ийг асуулт болгохгүй. |
| Screenshot-ийн model ID | [Албан model хуудас](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-live-translate-preview): model code, audio/text outputs, Live API, preview version. | Яг энэ model ID-г дараагийн implementation ба туршилтын metadata-д түгжинэ. Preview хувилбар тул тухайн огноо, setup-ийг хадгална. |
| Манай одоогийн Transcribe өөр API замтай | [Audio Transcription](https://ai.google.dev/gemini-api/docs/transcribe): file/Interactions input, language hints, verbatim/smart, formatting/normalization. [Transcribe model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe): Монгол `mn-MN`. | Өмнөх Transcribe туршилтыг тусдаа arm болгон хадгална; model нэрийг солиод Live туршсан гэж бичихгүй. |
| Whisper нь олон хэмжээ, хувилбартай | [OpenAI Whisper README](https://github.com/openai/whisper#available-models-and-languages): хэмжээ/параметр, хэл бүрийн чанарын ялгаа, Python audio window. `small` нь 244M параметр. | Манай Cafet small checkpoint-ийн сул үр дүнг бүх Whisper-ийн чанар болгож дүгнэхгүй. |
| Cafet-ийн нийтэлсэн тайлбар хязгаарлагдмал | [Cafet model card](https://huggingface.co/Cafet/whisper-small-mongolian): metadata, training hyperparameters, framework/eval мөрүүд. Eval WER бичсэн ч энэ хуудсанд манай ярианд шилжих баталгаа байхгүй. | Model card-ийн тоог хэрэглэгчийн бодит ярианы accuracy гэж нэрлэхгүй. |
| INT8 нь runtime-ийн сонголт | [faster-whisper](https://github.com/SYSTRAN/faster-whisper): CPU INT8 болон GPU тохиргооны жишээ. | CPU гэдгийг танилт муудах дан шалтгаан болгохгүй. Quantization-ийн нөлөөг тусгаарласан paired туршилтгүйгээр шалтгаан тогтоохгүй. |

Энэ удаа API/модель/кодын тодорхой асуултыг шалгасан. Шинээр 20 бүтэн өгүүлэл
уншсан гэж тайлагнахгүй. Аргын суурь нь [өмнөх 20 үндсэн уншлагын бүртгэл](09-stt-candidate-review-20261029.mn.md)-ийн
Whisper, low-resource ASR, corpus/domain shift, аргын сонголт ба үнэлгээний
хүрээтэй хэсгүүд. API зааврыг судалгааны өгүүллийн тоонд нэмээгүй.

## Одоогийн код ба хадгалсан туршилтын аудит

- `config/stt-development.json`, локал сонголт, `stt_mn.load_choice`,
  `voice_runtime.py`, retained protocol/raw model ID-уудыг тулгасан.
- Локал суурь нь `Cafet/whisper-small-mongolian`, pinned revision,
  CPU INT8; `language=mn`, `task=transcribe`, beam 5, temperature 0.
- Native audio-г mono 16 kHz PCM16 болгож, float waveform-д 32768-аар
  хуваадаг зам байна. Буруу хэл/task, эсвэл sample rate-ийн илэрхий
  тохиргооны зөрүү энэ шалгалтаар олдоогүй. Энэ нь боломжит бүх runtime
  алдаа байхгүй гэсэн баталгаа биш.
- Өмнөх 15 оролтын аудио hash/result association, pinned model checksum,
  12 matched гаралтын үг/тэмдэгтийн алдааг offline дахин тулгасан. Raw
  файл, reference, түүхэн оноог өөрчлөөгүй.
- Бодитоор хариу өгсөн Google model нь `gemini-3.5-transcribe` байсан.
  Screenshot-ийн Live Translate-ийг энэ багцад туршаагүй нь батлагдсан.
- Screenshot-ийн одоогийн микрофон/орчин ба хуучин багц ижил гэдгийг
  батлаагүй. Одоогийн зураг дангаараа бүх хэлсэн үгийн audio reference биш.

Хувийн per-clip гаралт, тоолол: `runtime/ii-evaluation-20261030/model-identity-audit.json`.
Тэдгээрийг нийтийн эхийн багцад нийтлэхгүй. Шинэ inference, сургалт, API
дуудлага эсвэл хүний үнэлгээ энэ аудитад хийгдээгүй.

## Яагаад зөв сонсогдсон текстийн raw WER өндөр байж болдог вэ?

Дараах нь **зохиомол тооцооны жишээ**, бодит модель туршсан дүн биш:

```text
reference: хоёр мянга хорин тав
hypothesis: 2025
```

Утга нь энэ жишээнд дүйцнэ. Raw whitespace WER-д reference 4 үгтэй;
нэгийг сольж, гурвыг хассанаар 4 алдаа / 4 үг = 100% гарна. Иймээс raw
WER нь нэр/тоо/оны утгын зөв байдал, хэрэглэгчийн засах хөдөлмөр болон
RAG-ийн амжилтыг дангаараа орлохгүй. Энэ нь дурын буруу тоог зөв болгох
шалтгаан биш: өөр он таньсан алдааг тусад нь хадгална.

Өмнөх тайланд тоо/үгийг чимээгүй дүйцүүлээгүй нь raw scoring-ийн зөв
зааг. Харин ганц aggregate WER-ээр хэрэглэгчид мэдрэгдэх чанарын давуу
тал эсвэл бүх Gemini хувилбарыг шийдэх нь хангалтгүй. Клип тус бүрийн
ялгаа, critical утга, task-ийг хамтад нь үзнэ.

## Шийдвэр ба хэрэгжүүлэх дараагийн хүрээ

1. Хэрэглэгчийн харуулсан Live Translate-ийн **Монгол input transcript**-ийг
   яг тэр model ID-тай тусдаа provider болгон холбоно. Одоогийн чатанд
   холбогдсон Transcribe-ийг Live Translate гэж дахин нэрлэхгүй.
2. Хадгалсан ижил аудиог ашиглавал хоёр API-д очсон PCM frame/sample,
   хэл/горим, chunk хэмжээ, session-ийн context-ийг тэмдэглэнэ. Live API-ийн
   зааварт mono PCM16 16 kHz, 100 ms chunk заасан. Transcribe-ийн файлын
   API payload-ийг Live endpoint рүү шууд хуулж болохгүй.
3. `inputTranscription.text`-ийг цуглуулна; завсрын/эцсийн transcript-ийн
   ялгааг шалгана. Орчуулсан аудиог тоглуулахгүй байсан ч API түүнийг
   үүсгэж болох тул дамжуулалт/өртгийг нуугаагүй тусдаа хүрээтэй байна.
4. Raw WER/CER-ийг хадгалж, тоо/он/нэрийн утгын хүний баталгаа, засах
   хугацаа, RAG task success-ийг тусад нь харьцуулна. Хараахан үзээгүй шинэ
   яриа хэрэгтэй; screenshot-ийн ганц амжилтыг ерөнхий accuracy болгохгүй.

**Одоогийн бодит төлөв:** судалгаа ба model-identity аудит дууссан; яг
Live Translate provider-ийн холболт болон шинэ paired inference хийгдээгүй.
Одоогийн түлхүүр, яриаг зөвшөөрөлгүй шинэ endpoint-д автоматаар илгээгээгүй.
Whisper дахин сургах, шинэ жин татах нь энэ асуудлын эхний шийдэл биш.
