# II · STT-ийн нэг candidate сонгох судалгаа — 2026.10.29

**Шийдвэр:** Cafet-ийг локал суурь хэвээр хадгалж, дараагийн харьцуулалтын түр candidate-аар **Gemini 3.5 Transcribe-ийн `verbatim` горим** сонгов. Энэ нь туршилтын чиглэлийн шийдвэр; үндсэн provider солигдсон, аудио илгээсэн, зардал гарсан эсвэл Gemini давуу болсон гэсэн үр дүн биш. Whisper-ийг дахин сургах нь заавал хийх ажил биш.

Хэрэглэгчийн шаардлагаар чиглэл сонгохын өмнө доорх **20 өөр өгүүллийн үндсэн текстийг** агентууд анхдагч бүтэн эхээс уншсан: арга, туршилтын нөхцөл, үр дүн, хязгаар, дүгнэлтийг хамруулав. Энэ нь хэрэглэгчийн өөрийн уншлагын бүртгэл, бүх хавсралт/эшилсэн эхийг нягталсан тайлан, кодын reproduction биш. MMS болон SeamlessM4T-ийн сонгосон уншлагыг нэмэлтээр тусад нь оруулсан; 20-д тооцоогүй. Provider-ийн заавар мөн судалгааны өгүүллийн тоонд орохгүй.

## Таван өнцгөөс харсан шийдвэр

| Өнцөг | Баримтаас харагдсан зүйл | Энэ багцын шийдвэр |
|---|---|---|
| Аргын механизм | Урт prompt, contextual pointer, KWS, synthetic adaptation, өөр ASR үйлчилгээ нь өөр өөр өөрчлөлт. TCPGen/CB-Whisper нь нэмэлт сургалттай. | Өмнө татгалзсан ижил decoder/prompt/synthetic сургалтыг дахин давтахгүй. Нэг бэлэн STT candidate-ийг тусад нь харьцуулна. |
| Монгол хэл ба бодит хэрэглээ | Англи benchmark, нийтийн уншсан яриа, Халхын Common Voice болон манай сургуулийн чөлөөт асуулт ижил тархалт биш. | Нэг хүний өмнө харсан 13-ыг observed dev гэж нэрлэнэ. Өгүүллийн gain, найзын сайн танилтыг манай үр дүн болгохгүй. |
| Үнэлгээ | WER нь нэр/тоо/үгүйсгэл, downstream task, human comprehension-ийг дангаар илэрхийлэхгүй. Normalization нь denominator-ийг өөрчилж болно. | Raw WER/CER, critical талбар, тогтсон RAG-ийн task, хугацаа/алдааг тусад нь хэмжинэ. |
| Төхөөрөмж, хугацаа, зардал | Шинэ локал жин/орчин татах нь зай, хөрвүүлэлт, inference-ийн зардал нэмнэ. Онлайн STT нь сүлжээ/үйлчилгээний хамааралтай. | Одоогийн Cafet болон жинг хадгална; Gemini-г бэлтгэсэн runner-аар хязгаарласан нэг харьцуулалт болгоно. Шинэ model download хийхгүй. |
| Өгөгдлийн эрх ба дахин ажиллуулах | Evaluation-only нь сургалт эсвэл гаднын API-д илгээх эрх биш. Source/reference/payload холилдвол шударга харьцуулалт алдагдана. | Аудио/reference-ийн hash, тохиргоо, анхны raw гаралтыг тусад нь хадгална. Гаднын дамжуулалт/төлбөрийн зөвшөөрлийг бэлэн багцтай нь авна; reference-ийг provider-д өгөхгүй. |

## 20 өгүүллийн уншлагын бүртгэл

Бүртгэлийн огноо 2026.10.29. arXiv-ийн хувилбарыг уншсан HTML/PDF-ийн metadata/header-аар тэмдэглэв; хэвлэлийн ACL/ISCA PDF-д venue/он/хуудас хэрэглэв. Доорх тоон дүн бүр тухайн өгүүллийн нөхцөлд хамаарна. Эдгээр нь энэ төсөлд шинээр гаргасан хэмжилт биш.

### 1. Robust Speech Recognition via Large-Scale Weak Supervision

[Анхдагч эх — arXiv:2212.04356v1](https://arxiv.org/html/2212.04356v1). **Уншсан:** §1–7, үндсэн текст. **Арга/өгөгдөл:** Whisper-ийн олон хэл, олон үүргийн weak supervision; low-resource болон zero-shot нөхцөл. **Хязгаар:** хэл бүрийн нөөц, normalization, decode fallback-аас дүн хамаарна; нэр/тоо эсвэл бүх Монгол ярианд баталгаа болохгүй. **Манай шийдвэр:** Cafet-ийн raw суурийг хадгалж, шинэ candidate-ийг ижил оролтоор хэмжих; paper-ийн default-аар өмнөх татгалзсан grid-ийг сэргээхгүй.

### 2. Distil-Whisper: Robust Knowledge Distillation via Large-Scale Pseudo Labelling

[Анхдагч эх — arXiv:2311.00430v1](https://arxiv.org/html/2311.00430v1). **Уншсан:** §1–10, үндсэн текст; тасарсан §7.2-ыг дахин нээсэн. **Арга/өгөгдөл:** англи ярианы том pseudo-labelled багцаар teacher/student distillation. **Хязгаар:** хурд, урт аудио, substitution-ийн trade-off; Монгол хэлд шилжсэн gain байхгүй. **Манай шийдвэр:** хурдны амжилтаар Монгол candidate болгохгүй; одоогийн жинг сольж татах үндэслэл биш.

### 3. Can Contextual Biasing Remain Effective with Whisper and GPT-2?

[Анхдагч эх — arXiv:2306.01942v1](https://arxiv.org/html/2306.01942v1). **Уншсан:** §1–6, үндсэн текст; байхгүй v2-ыг уншсан гэж тооцоогүй. **Арга:** Whisper-ийн үндсэн жинг царцаасан ч TCPGen pointer модулийг тусад нь сургана. **Өгөгдөл/хязгаар:** LibriSpeech/SLURP-ийн reference үг орсон contextual list нь бодит deployment-ийн жагсаалттай адил биш; ontology-тай нөхцөлийг тусад нь ялгана. **Манай шийдвэр:** reference-ээс hint үүсгэхгүй; `initial_prompt` нэмэхийг TCPGen хэрэгжүүлсэн гэж нэрлэхгүй.

### 4. CB-Whisper: Contextual Biasing Whisper using Open-Vocabulary Keyword-Spotting

[Анхдагч эх — LREC-COLING 2024, х.2941–2946](https://aclanthology.org/2024.lrec-main.262.pdf). **Уншсан:** 6 хуудасны үндсэн §1–5. **Арга:** TTS entity audio → Whisper encoder → сургасан CNN/KWS → богино contextual prompt. **Өгөгдөл/хязгаар:** хятад/англи/code-switching болон entity жагсаалтын нөхцөл; нэрийн recall нэмэгдэхэд нийт MER заавал сайжрахгүй. **Манай шийдвэр:** KWS сургалтыг урт prompt-оор орлуулахгүй. Нэрийн алдаа бүх алдааны гол шалтгаан гэдэг нь батлагдвал цааш судлах нэмэлт хувилбар.

### 5. A Domain Adaptation Framework for Speech Recognition Systems with Only Synthetic data

[Анхдагч эх — arXiv:2501.12501v1](https://arxiv.org/html/2501.12501v1). **Уншсан:** I–VI, үндсэн текст. **Арга/өгөгдөл:** домэйн тус бүрийн олон мянган synthetic жишээгээр Whisper adaptation; олон epoch-ийн сургалт. **Хязгаар:** домэйн хооронд муудах тохиолдол, TTS/өгөгдлийн тархалтын хамаарал. **Манай шийдвэр:** манай 200 update нь paper-ийн бүтэн reproduction биш. Synthetic дээрх өсөлт бодит 13-д шилжээгүй өмнөх сөрөг дүнг хадгалж, ижил сургалтыг шалтгаангүй давтахгүй.

### 6. LoRA: Low-Rank Adaptation of Large Language Models

[Анхдагч эх — arXiv:2106.09685v2](https://arxiv.org/html/2106.09685v2). **Уншсан:** §1–8, үндсэн текст. **Арга:** үндсэн жинг царцааж, бага rank-ийн өөрчлөлтийн матриц сургах; нэгтгэсний дараа нэмэлт inference layer шаардлагагүй байж болно. **Хязгаар:** өгүүллийн NLP туршилт нь Монгол ASR-ийн нотолгоо биш; rank, target layer, data сонголт нөлөөлнө. **Манай шийдвэр:** LoRA мөн бодит сургалт. Evaluation-only аудиогоор жин сургах эрх эсвэл заавал ахиц өгөх амлалт болохгүй.

### 7. Careless Whisper: Speech-to-Text Hallucination Harms

[Анхдагч эх — arXiv:2402.08021v1](https://arxiv.org/html/2402.08021v1). **Уншсан:** §1–7, үндсэн текст. **Өгөгдөл/арга:** англи AphasiaBank сегмент, 2023 оны API гаралт, non-vocal хэсэг ба hallucination-ийн шинжилгээ. **Хязгаар:** холбоо хамаарал нь дан механизмын баталгаа биш; тухайн хувилбар/хэлний дүнг одоогийн Монгол/Gemini-д шилжүүлэхгүй. **Манай шийдвэр:** яриагүй оролт, давталт, зохиосон нэмэлтийг WER-ээс тусад нь бүртгэнэ.

### 8. Transliteration-Aided Transfer Learning for Low-Resource ASR: A Case Study on Khalkha Mongolian

[Анхдагч бүртгэл — Electronics 2025, 14(6):1137](https://doi.org/10.3390/electronics14061137); [MDPI-ээс нийлүүлсэн уншсан бүтэн эх](https://www.researchgate.net/publication/389867217_Transliteration-Aided_Transfer_Learning_for_Low-Resource_ASR_A_Case_Study_on_Khalkha_Mongolian). **Уншсан:** §1–6, үндсэн текст. **Арга/өгөгдөл:** 147 цагийн Чахар train-ийн бичвэрийг кириллд галиглан, дараа нь Халхын CV17-ийн 3 цагийн train-аар тусгайлан сургана. **Дүн/хязгаар:** Whisper DFT43.02 → TFT31.45 WER, харин шууд нийлүүлсэн MDFT49.95; A6000 48 GB ашигласан. §3.2 дахь Whisper-д CTC loss хэрэглэсэн гэх тайлбар нь ердийн encoder–decoder сургалттай зөрдөг тул хэрэгжүүлэх жор болгон хуулж болохгүй. **Манай шийдвэр:** илүү өгөгдөл дангаараа ахиц биш; манай WER36.02-той өөр багцын дүнг шууд харьцуулахгүй.

### 9. FLEURS: Few-shot Learning Evaluation of Universal Representations of Speech

[Анхдагч эх — arXiv:2205.12446v1](https://arxiv.org/html/2205.12446v1). **Уншсан:** §1–5, үндсэн текст. **Арга/өгөгдөл:** 102 хэл, 16 kHz уншсан яриа; split, normalization, ASR/LangID/retrieval-ийн үнэлгээ. **Хязгаар:** уншсан өгүүлбэр нь өөрийн үгээр асуусан сургуулийн асуултыг төлөөлөхгүй; CER ба retrieval P@1 өөр хэмжүүр. **Манай шийдвэр:** нийтийн control-ийг хувийн observed dev-ээс тусад нь тайлагнана; normalization/reference хувилбарыг түгжинэ.

### 10. Common Voice: A Massively-Multilingual Speech Corpus

[Анхдагч эх — arXiv:1912.06670v2](https://arxiv.org/html/1912.06670v2). **Уншсан:** §1–7, үндсэн текст. **Арга/өгөгдөл:** хүн бичиж, өөр хүн сонсож баталсан уншсан яриа; speaker болон текстийн давхардлыг split хооронд хянана. **Хязгаар:** өгүүллийн DeepSpeech туршилт Монгол Cafet-ийн хэмжилт биш. Түүхэн CC0 тайлбар нь ашиглах яг release-ийн provenance/нөхцөлийг шалгахыг орлохгүй. **Манай шийдвэр:** хүний reference, speaker/session заагийг хадгална; нэг хүний alias-ийг олон хүн болгохгүй.

### 11. wav2vec 2.0: A Framework for Self-Supervised Learning of Speech Representations

[Анхдагч эх — arXiv:2006.11477v3](https://arxiv.org/html/2006.11477v3). **Уншсан:** §1–6, үндсэн текст; Appendix E-ийн алдааны тайлбарыг нэмэлтээр уншсан. **Арга:** masked contrastive pretraining → supervised CTC head/fine-tuning. **Хязгаар:** бага label-тай англи үр дүнгийн цаана асар их pretraining болон зарим дүнд хүчтэй LM бий; бэлэн encoder дангаараа Монгол ASR биш. **Манай шийдвэр:** шинэ encoder татах/сургахыг эхний алхам болгохгүй; spelling, нэр, acoustic алдааг тусад нь оношлоно.

### 12. XLS-R: Self-supervised Cross-lingual Speech Representation Learning at Scale

[Анхдагч эх — arXiv:2111.09296v2](https://arxiv.org/html/2111.09296v2). **Уншсан:** §1–6, үндсэн текст. **Арга/өгөгдөл:** олон хэлний self-supervised дүрслэл, task-specific head ба supervised fine-tuning. **Хязгаар:** ASR хүснэгт бүр Монгол хэлний үр дүн биш; зарим benchmark PER, зарим нь WER; model capacity өсөхөд бүх нөхцөлд өсөлт гараагүй. **Манай шийдвэр:** “Монголыг pretrain-д харсан” гэдгээр манай асуултын давуу талыг батлахгүй; head/tokenizer/license/compute-ийн бодит шаардлагыг тооцно.

### 13. An (unhelpful) guide to selecting the best ASR architecture for your under-resourced language

[Анхдагч эх — ACL 2023, х.1008–1016](https://aclanthology.org/2023.acl-short.87.pdf). **Уншсан:** §1–6, Limitations/Ethics, үндсэн текст. Anthology metadata-д “best”, PDF-д “right” гэсэн нэг өгүүллийн гарчгийн зөрүү бий; хоёр болгон тоолоогүй. **Арга/өгөгдөл:** 11 хэлд Kaldi/ESPnet/XLSR/Whisper харьцуулсан. **Хязгаар:** нэг архитектур бүх багцад ялаагүй; тогтсон recipe, жижиг багц, split-ийн speaker зааг ялгаатай. **Манай шийдвэр:** шинэ/том/алдартай гэдгээр candidate сонгохгүй; боломжит зардал, ижил оролтын нотолгоонд тулгуурлана.

### 14. Tandem Long-Short Duration-based Modeling for Automatic Speech Recognition

[Анхдагч эх — SIGUL 2024, х.331–336](https://aclanthology.org/2024.sigul-1.40.pdf). **Уншсан:** §1–6, үндсэн текст. **Арга/өгөгдөл:** Унгар Conformer дээр урт/богино ярианд хоёр model/adapter. **Хязгаар:** сургалтын нэмэлт зардалтай; §4.4-д train ба validation-ийн богино клипийг сургалтад хэрэглэсэн гэж бичсэн. Test-ээс хэцүү богино клипийг хассан дүн нь өөрөө gain биш. **Манай шийдвэр:** зөвхөн хугацаагаар алдаа задлах санааг авна; бүх 13 клипийг хадгалж, өөр split-ийн дүрмийг хуулж хэрэглэхгүй.

### 15. Statistical Testing on ASR Performance via Blockwise Bootstrap

[Анхдагч эх — arXiv:1912.09508v2, 2020.05.20](https://arxiv.org/pdf/1912.09508v2), PDF 6 хуудас. **Уншсан:** §1–6, theorem-ийн нөхцөл; appendix proof-ийг бүтнээр баталгаажуулаагүй. **Арга:** хамааралтай speaker/topic блокийг хадгалж, paired sample дээр ялгааны uncertainty тооцох. **Хязгаар:** нэг speaker-ийн 13 клипийг олон speaker мэт resample хийж population CI гаргах үндэслэл биш. **Манай шийдвэр:** denominator-тай descriptive paired дүнг эхэлж гаргана; хүмүүс хоорондын баталгаа зохиохгүй.

### 16. Semantic Distance: A New Metric for ASR Performance Analysis Towards Spoken Language Understanding

[Анхдагч эх — arXiv:2104.02138v1, 2021.04.05](https://arxiv.org/pdf/2104.02138v1), PDF 5 хуудас. **Уншсан:** §1–5, арга §2, setup §3, үр дүн §4. **Арга/өгөгдөл:** англи hypothesis-ийн semantic зай ба downstream ойлголт; том дотоод багц, өөрчилсөн hypothesis/pseudo label ашигласан. **Хязгаар:** англи embedding/pseudo NER нь Монгол хүний үнэлгээ биш. **Манай шийдвэр:** WER-тэй хамт нэр/тоо/үгүйсгэл, ижил RAG-ийн task шалгана; шинэ semantic модель татаж “үнэн” оноо болгохгүй.

### 17. What is lost in Normalization? Exploring Pitfalls in Multilingual ASR Model Evaluations

[Анхдагч эх — arXiv:2409.02449v4, 2024.11.09](https://arxiv.org/pdf/2409.02449v4), PDF 6 хуудас. **Уншсан:** §1–6 ба resource appendix. **Арга/өгөгдөл:** олон хэл, ялангуяа Энэтхэг хэлний бичгийн тэмдэг/normalization WER-д хэрхэн нөлөөлөхийг шалгасан. **Хязгаар:** манай Монгол багцын шинэ дүн биш; тэмдэг арилгах нь word denominator хүртэл өөрчилж болно. **Манай шийдвэр:** хуучин raw scoring policy-г царцааж, тоо–үг/Latin–Cyrillic утгын дүйцлийг тусдаа semantic талбарт шалгана.

### 18. Why Aren’t We NER Yet? Artifacts of ASR Errors in Named Entity Recognition in Spontaneous Speech Transcripts

[Анхдагч эх — ACL 2023](https://aclanthology.org/2023.acl-long.98.pdf), PDF 16 хуудас. **Уншсан:** үндсэн §1–7, span alignment §2, өгөгдөл §3, туршилт §4, хязгаар §6; бүх appendix жишээ/номзүй биш. **Арга/өгөгдөл:** англи SWNE/OntoNotes/Earnings21; ASR token солих/хасах/нэмэхэд entity span тааруулах алдаа үүснэ. **Хязгаар:** NER нь gold transcript дээр ч алддаг. **Манай шийдвэр:** typed reference → RAG болон raw STT → RAG-ийг зэрэг хадгалж, downstream бүх алдааг ASR-д хамаатуулахгүй.

### 19. Perceptual and Task-Oriented Assessment of a Semantic Metric for ASR Evaluation

[Анхдагч эх — Interspeech 2023](https://www.isca-archive.org/interspeech_2023/rugayan23_interspeech.pdf), PDF 5 хуудас. **Уншсан:** §1–5, survey §3.1, downstream §3.2, үр дүн §4. **Арга/өгөгдөл:** Норвеги 30 текстийн хос, 40 хүний survey; acoustic-semantic metric ба task proxy. **Хязгаар:** аудио сонсгосон TTS судалгаа биш; өөрчилсөн hypothesis/pseudo downstream label бий. **Манай шийдвэр:** хүний сонсголын дүнг semantic metric-ээр нөхөхгүй; critical rubric-ийг эхэлж тодорхойлно.

### 20. Constructing a Multimodal, Multilingual Translation and Interpreting Corpus: A Modular Pipeline and an Evaluation of ASR for Verbatim Transcription

[Анхдагч эх — CLiC-it 2024](https://aclanthology.org/2024.clicit-1.42.pdf), PDF 7 хуудас. **Уншсан:** §1–5, pipeline §3, verbatim/training/error analysis §4, хүснэгт 2–4. **Арга/өгөгдөл:** англи/итали verbatim transcript, жижиг fine-tuned ба том ASR-ийн харьцуулалт. **Хязгаар:** англид гарсан ranking итали дээр адил биш; filler, давталт, тасалдсан үгийг гаргах нь жигд бус. **Манай шийдвэр:** `verbatim`-ийг сонгож, grammatical cleanup-ийг raw gain гэж тооцохгүй.

## Нэмэлт сонгосон уншлага — 20-д тооцоогүй

- [Scaling Speech Technology to 1,000+ Languages — MMS, arXiv:2305.13516v1](https://arxiv.org/pdf/2305.13516): §3.1 data/alignment/filtering/split, §4.2–4.3, §5.1–5.5 уншсан; бүх 41 хуудас биш. CTC + language adapter/head, Whisper-тай харьцуулахад external n-gram LM хэрэглэдэг. Нэг speaker-тэй эхийн split-ийг өөр benchmark-ээр нэмж шалгах шаардлагыг тайлбарласан. [Албан checkpoint](https://huggingface.co/facebook/mms-1b-all) 1B параметр, CC-BY-NC-4.0. Манай эхний candidate болгож автоматаар татахгүй.
- [SeamlessM4T, arXiv:2308.11596v3](https://arxiv.org/html/2308.11596v3): §4.1–4.2, §4.4, §5.2-ийн human/omission/limitations, §5.3 уншсан; бүх тайлан биш. ASR, орчуулга, TTS хэмжүүрийг ялгана. Автомат S2ST metric өндөр ч хүний үнэлгээ дор байх зөрүү гарсан; дөрвөн өндөр нөөцтэй хэлний шуугианы дүн Монголын баталгаа биш. v1 paper-ийн дүнг v2 checkpoint-ийн дүн гэж солихгүй.

## Албан API заавар ба түр candidate

2026.10.29-нд [Gemini 3.5 Transcribe model](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe), [Developer API transcription](https://ai.google.dev/gemini-api/docs/transcribe), [үнийн хүснэгт](https://ai.google.dev/gemini-api/docs/pricing), [өгөгдөл ашиглах нөхцөл](https://ai.google.dev/gemini-api/terms)-ийн холбогдох хэсгийг дахин шалгав. API заавар нь дээрх 20 судалгааны өгүүллийн нэг биш.

Түр candidate нь файлын `gemini-3.5-transcribe`; Developer API-ийн Interactions хүсэлт, `language_codes=["mn-MN"]`, `mode={"type":"verbatim"}`. Smart cleanup, custom vocabulary, diarization, word timestamps-ийг энэ нэг харьцуулалтад идэвхжүүлэхгүй. Тусгай transcript үйлчилгээний боломжийг ерөнхий audio understanding/Live API эсвэл Cloud-ийн өөр endpoint-той хольж хэрэгжүүлэхгүй. Баримтад Монгол хэл жагсаалттай байгаа нь манай accuracy-ийн баталгаа биш.

Энэ сонголтын үндэслэл нь шинэ local жин/орчин татахгүйгээр өөр бэлэн recognizer-ийн алдааг Cafet-тай харьцуулж болох явдал. Ижил тохиргоотой эхний бүх raw гаралтыг хадгална; reference/хүлээсэн асуулт/сургуулийн зөв хариуг API input-д өгөхгүй. Ямар нэг provider-ийн `verbatim` нэр нь төгс хуулбарлах баталгаа биш.

## Гаралтаас өмнө тогтоосон харьцуулалтын шалгуур

**Хэмжих эхлэл:** хуучин 13 клип, нийт 152 секунд; нэг speaker, өмнө үзсэн observed development багц. Анхны файлууд 44.1 kHz mono PCM16; хоёр arm-д яг ижил original byte/hash-тай файлыг өгнө, тэдгээрийг дарж resample хийхгүй. Cafet-ийн хадгалсан raw суурь **67/186 = WER36.02%**, **184/1089 = CER16.90%**. 67/184 нь үг/тэмдэгтийн алдааны хоёр тоо; WER-ийн хуваарь биш. Шинэ хүн/heldout benchmark гэж нэрлэхгүй. Анхны аудио, баталсан reference, scoring policy, код/жингийн hash-ийг өөрчлөхгүй. Шинэ paired run-ийн Cafet суурь зөрвөл нууцаар шинэ тоогоор сольж gain тооцохгүй; оролт/хувилбар/decoder-ийн зөрүүг эхэлж шийднэ.

Өмнөх ижил 13-ын хадгалсан бусад туршилтад blgn94 104, nrlt133, turbo-blgn94 102, VAD78, beam1 86 үгийн алдаатай; Cafet67-оос давуу болоогүй. Эх нь `results/stt-comparison-20261010/summary.json`. Эдгээр observed dev дүнг шинэ inference гэж тооцохгүй, ижил хувилбаруудыг энэ багцад дахин ажиллуулахгүй.

Өмнө бэлэн болсон 3 секундийн хоёр хяналтын аудио буюу нэмэлт 6 секундыг тусад нь шалгана; нийт хүсэлтийн бэлтгэл **13 бодит +2 хяналт =15 файл, 158 секунд**. Хяналтын файлыг хүн ярьсан шинэ бичлэг болгохгүй, тэдгээрийг 13-ын WER denominator-д оруулахгүй. Яриагүй оролтоос зохиосон transcript/нэр/тоо нэмэхгүй байхыг тусдаа хамгаалалт болгоно.

| Шалгуур | Candidate-ийг цааш авч үзэх босго | Тайлагнах хүрээ |
|---|---|---|
| Raw WER | 186 reference үг дээр **≤60 үгийн алдаа** | Дор хаяж 7 алдаагаар буурсан байх; ≥10% relative reduction-ийн урьдчилсан практик босго. Хүний/general gain биш. |
| Raw CER | 1089 reference тэмдэгт дээр **≤184 алдаа** | WER буурахад тэмдэгтийн нийт алдаа муудахгүй. |
| Critical талбар | Суурийн зөв нэр/тоо/он/үгүйсгэлийг шинээр алдах **0** | Case бүрийн span/утгын rubric, бодит review шаардлагатай; AI оноог хүний оноо болгохгүй. |
| Downstream | Тогтсон corpus/code, typed/raw paired task-д **сууриас шинэ regression 0** | Reference-ээр асуусан RAG алдаа ба STT-ээс үүссэн алдааг салгана; хүний шийдээгүй мөр pending. |
| Хугацаа/алдаа | Амжилттай хүсэлт бүрийн upload + inference + cleanup нийт wall time **≤10 секунд** | Үе шат, timeout/provider failure, sample count-ийг тусад нь хадгална. Cafet-ийн cold model load тусдаа. Энэ нь хэмжсэн p95 эсвэл бодит үр дүн бус босго. |
| Шийдвэр | Бүх шалгуур нийлж тэнцсэн үед л дараагийн dev баталгаажуулалтын candidate | Хуучин 13-аар үндсэн provider-ийг автоматаар солихгүй. Муудсан/дутуу дүнг хадгална. |

Нэг хүний хамааралтай 13 клипээс хүмүүс хоорондын CI гаргахгүй. Урт/богино клип, нэр/тоо, S/D/I-г тусад нь харуулна; хэцүү клипийг хасаж нийт WER бууруулахгүй. Шинэ audio/reference ирвэл dev-v2 болгож baseline ба candidate-ийг хоёуланг нь түүн дээр хэмжинэ. Хүний шинэ бичлэг, сонссон reference, task/TTS rating **хийгдээгүй бол pending** хэвээр.

## Зардал, зөвшөөрөл, нийтлэх хил

Албан үнийн хүснэгтийн тухайн үеийн ойролцоолол ~$0.005/мин. Хяналттайгаа 158 секунд буюу 2.63 минутын нэг pass ~$0.013; output/billing-ийн хэлбэлзэлд **ойролцоогоор $0.02** гэж бэлтгэлд тооцсон. **$0.10 нь санал болгосон нийт дээд төсөв; хэрэглэгчийн төлбөрийн зөвшөөрөл биш.** Бодит үнэ, billing project/tier, тухайн хүсэлтийн usage-ийг ажиллуулах үед дахин тулгана.

Хувийн аудиог үнэгүй tier-д илгээхгүй: үйлчилгээний нөхцөл input/output-ийг сайжруулалтад ашиглах болон хүний review-ийн боломжийг тайлбарласан. Paid tier-ийн өөр нөхцөл нь ч автоматаар дамжуулах эрх үүсгэхгүй. Тодорхой файлын hash/хугацаа, илгээх provider/model/горим, өгөгдлийн нөхцөл, төсөв, гаралтын хадгалалттай бэлэн хүсэлтийн багцыг хэрэглэгчид үзүүлж зөвшөөрөл авсны дараа л online run хийнэ.

Нийтийн GitHub-д энэ аргын тайлбар, шалгасан код/тест/зохиомол fixture орно. Хувийн PDF, audio/reference, DB, model, token, runtime packet/raw гаралтыг нийтлэхгүй. Том backup, архив, давхар clone үүсгэхгүй. Энэ тэмдэглэл өөрөө шинэ ASR/TTS inference, сургалт, таталт, хүний үнэлгээ эсвэл чанарын өсөлт болсон баримт биш.

## Хэрэгжүүлсэн runner ба үргэлжлүүлэх нь

`tools/compare_stt_candidate.py prepare --manifest <private-manifest> --output <new-private-packet>` нь runtime дотор шинэ packet бэлтгэнэ; сүлжээ болон модель дуудахгүй. `run --manifest ... --packet ... --output <new-run> --approval ...` нь яг protocol/manifest hash-тай хэрэглэгчийн бодит зөвшөөрөл, орчны `GEMINI_API_KEY`-ийг шаарддаг. Хоосон зөвшөөрлийн template тэнцэхгүй. Нэг packet нэг pass-д хэрэглэгдэнэ; гаралтын өөр нэрээр хүсэлтийн budget-ийг дахин эхлүүлэхгүй. `summarize --run <private-run>` нь raw файлаас тооцоолох бөгөөд provider-ийг солихгүй.

Одоогийн бэлэн packet нь хувийн `runtime/stt-candidate-20261029/review-v3/`;15 файл158s.480output-token/хүсэлт гэсэн хязгаартай болгоомжтой token тооцоо **$0.0943**;ердийн минутын тарифын ~$0.02 тойм тооцоогоос өөр зориулалттай. Хоёулаа бодит bill-ийн баталгаа биш.18 critical literal span-ыг output-оос өмнө reference-ээс царцаасан;энэ нь AI draft,шинэ хүний баталгаа биш. Эргэлзээтэй он/мөнгөний утгыг засаж таамаглаагүй.

39 runner тестийг багтаасан129 чиглэсэн тест PASS. Тестийн үед208 код/хөрөнгийн hash drift0;эх аудио/reference,хоёр DB,Cafet asset-уудтай32 хамгаалсан файл drift0. Эдгээр нь зохиомол fixture/transport ба offline packet-ийн шалгалт;бодит Gemini-тай амжилттай ажилласан эсвэл raw STT сайжирсан гэсэн дүгнэлт биш. Бодит run-ийн дараа bound RAG input,төрөлжсөн S/D/I,клип тус бүрийн хугацаа ба хүн үнэлэх template гарна;хүний үнэлээгүй мөр pending хэвээр.
