# II · Ганц Gemini горим, түлхүүрийн засвар ба үр ашигтай урсгал — 2026.10.30

Хэрэглэгч дуу танихад түр хугацаанд ганц Gemini 3.5 хэрэглэх, API түлхүүр
давтан нэхэхийг болиулах, Whisper-ээс өөр хэрэгжих боломжийг GitHub-ээс
судлахыг хүссэн. Дуу таних үндсэн зам нь `gemini-3.5-live-translate-preview`.
Сургуулийн хариулт өмнөх хувилбартай эхтэй RAG-аар, дуут гаралт одоогийн
TTS-аар явна. Эцсийн STT сонголт 2026.11.02-ны хэрэглэгчийн шийдвэр хүртэл түр.
Энэ нь сургуулийн баталсан уулзалтын тов эсвэл II хэсэг бүхэлдээ дууссан төлөв биш.

## Шалтгаан ба засвар

Өмнөх түлхүүр зөвхөн процессийн санах ойд байсан. Сервер шинэчлэхэд түлхүүр
мартагдаж, таван оролдлогын бэлтгэлийн хязгаар дахин тохируулахыг шаардсан.
Холболтын кодын тестийг бодит танилттай андуурч тайлагнах нь хангалтгүй
байсныг энэ засварын бодит API шалгалтаар ялгав.

- Түлхүүрийг Windows-ийн одоогийн хэрэглэгчтэй холбосон DPAPI-аар шифрлэж,
  ignored runtime-д хадгална. UI_FORBIDDEN хэрэглэж, LOCAL_MACHINE өгөөгүй.
  Plaintext key файл, browser storage, Git-д орохгүй. Шинэ сервер
  configured/ready/key_persisted төлөвөө сэргээсэн.
- Main UI ба API зөвхөн Gemini Live хэрэглэнэ. Provider сонголт, бичлэг
  бүрийн нэмэлт чагт, ердийн хэрэглээний таван оролдлогын хязгаарыг хасав.
  Хэрэглэгч бичлэгээ дуусгах эсвэл файл сонгоход танилт эхэлнэ.
- Өмнөх хуудсын дөрвөн талбартай тохиргоо түлхүүрийг арилгаж, хуучин
  хязгаарт буцаахгүй. Квотын алдаа түлхүүрийг мартах шалтгаан биш.
- Ижил WAV, model, setup SHA-д холбосон 16 хүртэл үр дүнг 30 минут санах ойд
  дахин ашиглана. Cache hit нь шинэ provider call биш гэдгийг metadata-д
  ялгана. Түлхүүр солиход cache цэвэрлэгдэнэ.
- `mn-MN` input hint нэмсэн. Өөр хэл таньсан үед raw текстийг чимээгүй
  засахгүй; Монгол хэлээр танигдаагүйг харуулна. Орчуулсан гаралтыг RAG
  оролт болгохгүй.

DPAPI-ийн хэрэглэгчийн зааг ба non-interactive сонголтыг
[Microsoft-ийн албан API тайлбартай](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
тулган, зохиомол key-ээр native roundtrip шалгасан. Энэ нь Windows хэрэглэгчийн
орчны хамгаалалт; нэвтэрсэн хэрэглэгчийн орчныг бүрэн дайсан гэж үзсэн баталгаа биш.

## Бодит functional шалгалт

Google-ийн setup амжилттай болсон. Хувийн хүний хуучин аудиог дахин
илгээхгүйгээр Edge TTS-ийн зохиомол Монгол control-уудыг ашиглав. Нийт дөрвөн
Live танилтын оролдлого, нэг тусдаа аудиогүй setup probe хийсэн. Automatic
retry болон өөр provider руу fallback хийгээгүй.

| Control | Бодит ажиглалт | Хүрээ |
|---|---|---|
| Богино 4.344s, auto language | Япон transcript | Буруу хэл таньсан failure |
| Яг ижил богино WAV, `mn-MN` hint | Дахин япон transcript | Hint уг тохиолдлыг засаагүй |
| Урт Монгол control | Монгол transcript; Коосэн нэр, нэмэлт үг дээр алдаа | Монгол текст буцаасан; төгс танилт биш |
| Хураамжийн 7.944s control | Монгол transcript; «бүртгэлийн» орхигдсон, нэр/үгийн алдаа | Main API, raw lineage, cache, эхтэй хариултын шалгалт |

Урт ба богино control өөр аудиотой тул ялгааг hint-ийн paired gain гэж
тооцохгүй. Эдгээр нь хүний яриа, heldout benchmark, human accuracy биш.
Quiet window нь текстийн төгсгөл бүрэн ирснийг дангаар батлахгүй; хүн
нягтлаад асуултаа илгээдэг зааг хэвээр.

Fee control-ийн typed reference нь ASR-ээс өмнө бэлтгэгдэж, хадгалсан
журмын бүртгэлийн **20,000 төгрөг** гэсэн заалтад хүрсэн. Raw STT нь
«элсэлтийн хураамж» болсон тул эхний main run өөр HTML эхээр ижил дүнг
хариулсан боловч exact-source/answer шалгуур тэнцээгүй. RAG C зам 31.349s,
STT 17.096s зарцуулсан. Анхны гаралт болон илүүдэл эхийн хэсгийг хадгалсан.

Засвар нь fee amount intent-д заавал «бүртгэ-» гэсэн хэлбэр шаардахгүй болгов.
Хариуны тоог кодод оруулаагүй: олдсон журмын бүтэн заалтыг эхээр нь хуулна.
Олимпиад, буцаан олголт, байрны төлбөр, зэрэг асуусан сургалтын төлбөрийг
ганц заалтаар орлуулахгүй. «Сургалтын төлбөрөөс тусдаа» гэсэн тайлбарыг хоёр
төлбөр хоёуланг нь асуусантай андуурахгүй.

Хадгалсан raw текст, аудионы SHA, анхны retrieved context-ийг тулгахад шинэ
extract нь typed reference-ийн яг PDF заалт, source ID-г сэргээсэн. Нэмэлт
Google танилтгүй. Эхний C хариултын бодит TTS үүсэж, 13.968s аудио decode
болсон; хүн сонсож зөв ойлгосны баталгаа биш.

## GitHub-ээс уншсан хүрээ ба шийдвэр

2026.10.30-нд холбогч ба анхдагч repository-оос дараах сонгосон README/кодыг
уншсан. Бүх repository-г аудитласан, бүгдийг суулгасан, шинэ 20 өгүүлэл уншсан
гэж тооцохгүй. Ижил II чиглэлийн үндэслэлд [өмнөх 20 өгүүллийн
бүртгэлийг](09-stt-candidate-review-20261029.mn.md) дахин ашигласан.

| Repository, уншсан хүрээ | Манай хэрэгцээ ба шийдвэр |
|---|---|
| [Google Live examples](https://github.com/google-gemini/gemini-live-api-examples/blob/main/command-line/python/translate.py): translation CLI-ийн queue/pacing/receive/shutdown | 16 kHz PCM16, 100 ms хэсэг, duplex хүлээн авалтыг тулгасан. Манай recorded-clip урсгалд тохируулсан |
| [Google Python SDK](https://github.com/googleapis/python-genai): README-ийн API/migration, live/converter/auth/Transcription type-ийн сонгосон хэсэг | Setup талбарын байрлал, header auth, finished утгыг тулгасан. Энэ засварт SDK migration шаардаагүй |
| [Google web console](https://github.com/google-gemini/live-api-web-console/blob/main/src/lib/audio-recorder.ts): AudioRecorder жижиг файл | Browser AudioWorklet → PCM16 ба mic cleanup нь дараагийн latency ажлын суурь. Одоогийн capture-ийг true streaming болгосон гэж тайлагнаагүй |
| [Gemini Translate + LiveKit](https://github.com/google-gemini/gemini-live-translate-livekit): setup/architecture/security | Нэг хэлний session-ийг олон сонсогчид хуваах загвар. Нэг хэрэглэгчийн одоогийн засварт media server нэмээгүй |
| [LiveKit Agents](https://github.com/livekit/agents): features/running/license | WebRTC, scheduling, turn detection нь олон session-д боломжтой. Source-ID сонголттой RAG-ийг framework agent-аар сольсонгүй |
| [Pipecat](https://github.com/pipecat-ai/pipecat): README pipeline/transport | Speech/LLM/TTS үе шатыг салгаж хэмжихэд хэрэгтэй. Шинэ dependency нэмэхээс өмнө хэмжсэн bottleneck-ийг зассан |
| [Silero VAD](https://github.com/snakers4/silero-vad): README боломж, LICENSE | Яриа байгаа эсэхийг ялган provider call багасгах боломж. STT/Монгол танилт биш; энэ засвараар шинэ жин татаж, аудиог тайраагүй |
| [JiWER](https://github.com/jitsi/jiwer): README metric/empty-reference | WER/CER ба дуугүй оролтын hallucination тоолоход хэрэгтэй. Түүхэн denominator өөрчлөөгүй |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz): README metrics/performance/license | Том scoring багцын edit distance-д боломжтой. Name similarity-г correctness эсвэл silent STT засвар болгоогүй |

Silero-ийн badge-д найдалгүй [LICENSE](https://github.com/snakers4/silero-vad/blob/master/LICENSE)
доторх MIT нөхцөлийг тулгасан. Нийтийн жишээний бүх кодыг хуулж, API key-г
frontend-д тараах загвар сонгоогүй.

Бодит үр ашиг нь түлхүүр давтан оруулахыг арилгасан, ижил аудионы давхар
provider call-ийг багасгасан, мэдэгдэж буй fee талбарыг хэрэггүй model
selection-ээс салгасан өөрчлөлт юм. LiveKit/Pipecat-аар бүх системийг дахин
бүтээсэн эсвэл шинэ STT жин сургаж чанар өсгөсөн ажил хийгдээгүй.

## Нотолгоо ба үлдсэн хүрээ

Код: gemini_credentials.py, gemini_stt_runtime.py, gemini_live_transport.py,
voice_runtime.py, demo_server.py, demo/index.html, source_fields.py.
364 холбогдох автомат шалгалт PASS; native Windows DPAPI, HTTP, actual inline
JS handler, raw lineage, source/field regression орсон. Энэ тоо human accuracy
эсвэл дипломын completion хувь биш.

Хувийн raw/runtime artifact нь runtime/ii-evaluation-20261030/synthetic-*/,
owner/deployment proof ба completion checkpoint-д. Key, аудио, raw JSON
автоматаар нийтлэгдэхгүй. Натив браузерийн input/playback шалгалт URL policy
болон app approval timeout-аас баталгаажаагүй; HTTP/JS шалгалттай адил гэж
үзэхгүй. I-ийн хүний review, II-ийн шинэ хүний paired үнэлгээ, III-ийн
диплом/байршуулалт хэвээр үлдсэн.
