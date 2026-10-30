# II · Gemini-ийн бодит хэрэглээний эхний хэмжилт — 2026.10.30–31

Нэг хүний өмнө нь сонсож баталсан шинэ бичлэгийг хэрэглэгчийн тусдаа
зөвшөөрлөөр яг `gemini-3.5-live-translate-preview` дээр нэг удаа хэмжив.
Бичлэг, reference, per-clip оноо ба raw гаралт нь хувийн runtime-д хадгалагдана.
Өмнөх 15 файлын Transcribe туршилтын эрхийг дахин ашиглаагүй. Энэ нь
development-ийн нэг жишээ; шинэ хэлэгчийн benchmark, ерөнхий accuracy,
моделийн чанарын өсөлт, II хэсэг бүхэлдээ дууссан үр дүн биш.

## Урьдчилан түгжсэн нөхцөл

- Хүний сонсож баталсан reference event ба WAV-ийн SHA, хугацаа, model/setup
  SHA, кодын hash, нэг cloud оролдлого, $0 зардлын зөвшөөрлийг протоколд түгжсэн.
- Аудио Google руу очсон; reference болон сургуулийн зөв хариултыг provider-ийн
  context болгоогүй. Үндсэн серверийн хамгаалсан түлхүүрийг дахин оруулаагүй.
- Хэрэглэгч Free tier гэж баталсан; апп billing-ийг бие даан батлаагүй.
  Автомат retry, paid fallback, шинэ Whisper сургалт, модель таталт хийгээгүй.
- Typed spoken reference ба Gemini raw-ийг ижил эхийн release дээр хоёр
  локал RAG хүсэлтээр шалгасан. Гол raw гаралт, татгалзлыг анхны хэвээр хадгалсан.

Google-ийн [Live Translation заавар](https://ai.google.dev/gemini-api/docs/live-api/live-translate)
оролтын `inputTranscription` болон хэл танилтын хязгаарыг тайлбарладаг.
Энэ модель нь translation pipeline тул өөр Transcribe model-ийн custom
vocabulary/instruction зааврыг түүнд шууд шилжүүлээгүй. Нэг ижил model ID хэвээр.
[Албан үнэ](https://ai.google.dev/gemini-api/docs/pricing)-д Live Translate-ийн
Free tier оролт/гаралт үнэгүй квоттой; [үнэгүй үйлчилгээний нөхцөл](https://ai.google.dev/gemini-api/terms)-д
өгөгдлийг сайжруулалтад ашиглах, хүн хянаж болохыг тайлбарласан.

## Бодит ажиглалт ба хийсэн засвар

Raw текстэд бичлэгийн хэлбэрийн ялгаа болон reference-д байхгүй он илэрсэн.
Хэлбэрийн ялгаа бүр утгын алдаа гэсэн үг биш. Нэмэлт он асуултын хүрээнд
нөлөөлж raw RAG хариулт өгөхөөс татгалзсан; typed reference эхтэй хариулт авсан.
Эхийн оноор raw STT-ийн оныг чимээгүй сольж, RAG хамгаалалтыг сулруулаагүй.

Дараах засвар хэрэгжсэн:

1. Хүний шалгалтын хуудас үндсэн чаттай ижил ганц Gemini зам ашиглана.
   Локал хадгалалт нь cloud дамжуулах зөвшөөрөл болохгүй. «Google руу илгээж
   Gemini-ээр таних» гэсэн илэрхий үйлдэл, баталсан reference хоёул шаардлагатай.
2. Аудио илгээхээс өмнө локал session token-ийг авна. Model, input hash,
   provider, орчуулгын гаралт хэрэглээгүй эсэхийг шалгана; reference илгээхгүй.
3. WER/CER, S/D/I, wall/provider хугацаа, RTF, cache-ийг тусад нь хадгалж
   харуулна. Түүхэн normalization хэвээр: NFC/casefold, цэг тэмдэг→зай,
   CER-д зай орохгүй; тоо–үгийг дүйцүүлж оноо бууруулахгүй.
4. Үндсэн чат raw-д байгаа оны цифрүүдийг ил гаргана. Шалгалтын хуудсанд
   reference/raw оны жагсаалтын зөрүү харагдана. Энэ нь literal шалгалт;
   үгээр бичсэн тооны утга, хүний сонсголын зөв байдлыг автоматаар шүүхгүй.
5. Хуучин хадгалсан өөр STT-ийн raw-г түүхэн гэж ялгана. Хадгалсан
   consent/reference/raw/12 сонсголын эх файлуудыг өөрчлөөгүй.
6. Оны шүүлтээр хоосорсон evidence-ийг «багшийн тоо батлагдаагүй» гэж
   тайлбарлаж байсан дарааллын алдааг зассан. Татгалзах хамгаалалт хэвээр;
   энэ хайлтаар дэмжигдээгүй оныг нэрлэж асуултын оныг нягтлахыг хүснэ.
   Retrieval context-д он байхгүй нь хүн тэр оныг хэлээгүйг батлахгүй.

Хэмжилтэд [өмнөх 20 өгүүллийн уншлага](09-stt-candidate-review-20261029.mn.md)-ийн
reference, normalization, domain/speaker хязгаарын хэсгийг дахин хэрэглэсэн.
[JiWER-ийн primary README](https://github.com/jitsi/jiwer)-д WER/CER-ийг edit
distance-ээр тооцох хүрээг тулгасан; шинэ dependency нэмээгүй. Төслийн score.py
болон deterministic minimum-edit alignment хэрэглэв. S/D/I задаргаа нь
ижил зайтай олон alignment-аас нэг тогтсон сонголт; акустик шалтгааны баталгаа биш.

## Анхны үр дүн ба дараах development replay

Анхны typed/raw харьцуулалт дууссаны дараа тусдаа follow-up төлөвлөгөө
бичсэн. Хүн өмнө нь баталсан reference-ийг raw ID-тай edited-lineage болгон
локалд дахин илгээхэд typed-ийн яг эх/хариулт сэргэсэн; response-bound TTS
үүсэж decode тэнцсэн. Raw текст хадгалагдсан, manual verification гэж
зарлаагүй. Энэ нь хүн шинээр зассан/сонссон task success биш.

Follow-up-д шинэ Google аудио дуудлага 0. Анхны protocol, raw, оноо, татгалзлыг
дарж өөрчлөөгүй. Хүний засах хугацаа, semantic critical score, шинэ TTS
comprehension хэмжээгүй; null хэвээр. Нэг хүсэлтийн latency-г p50/p95 эсвэл
provider-ийн нийт хурд болгож дүгнээгүй. Одоогийн зам бичлэг дууссаны дараа
аудиог paced stream-ээр илгээдэг; браузерээс ярьж байх үеийн true streaming биш.

## Шалгалт ба үргэлжлэл

185 холбогдох тест PASS: хүний journal/resume, Gemini consent/token/model/hash,
metric/empty-output, оны literal review, raw lineage, voice HTTP, портатив болон
жинхэнэ inline JS handler-ийн fixture шалгалт. Сүүлийн түүхэн raw label-ийн
засварт хүний хуудасны 41 шалгалтыг дахин ажиллуулсан. Эдгээр нь бодит STT
accuracy биш. Нийтэд хувийн raw/оноо/API түлхүүр/аудио нийтлээгүй.

Дараах оны тайлбарын засварт 202 RAG/source regression, 24 HTTP шалгалт
тус тус PASS. Хадгалсан context дээрх offline replay болон ажиллаж буй
localhost API дахь нэг typed development replay зөв оны тайлбар гаргасан;
raw асуулт, анхны татгалзал, оноо хэвээр. Шинэ ASR/Google/LLM/TTS дуудлага,
хүний шинэ үнэлгээ үүсгээгүй. Эдгээр suite-ийн тоог өмнөх 185-тай нэмэхгүй.

Хувийн эх: `runtime/gemini-real-use-20261030/` дахь protocol, authorization,
first-raw, measurement, typed/raw RAG, follow-up replay, TTS ба SHA шалгалт.
Холболтын өмнөх засвар [тусдаа тайланд](12-gemini-single-provider-repair-20261030.mn.md).
Дараагийн хүний ажил нь өөрийн шинэ асуулт, нэр/тоо/оны утгын нягтлал,
сонссон мэдээлэл ба засах хөдөлмөрийн үнэлгээ. Ганц Gemini горим 2026.11.02-ны
хэрэглэгчийн эцсийн шийдвэр хүртэл хэвээр; хийсвэр хүн/оноо/accuracy үүсгэхгүй.
