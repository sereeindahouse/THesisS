# Унших өгүүллийн бүрэн жагсаалт ба 14 цагийн долоо хоногийн хуваарь (2026.11.22)

**Хүсэлт (хэрэглэгч, 2026.11.22):** Монгол судалгааны ажлыг оролцуулаад унших ёстой бүх өгүүллийг 127 систем дээр долоо хоногоор хувааж тавих; долоо хоногт 14 цаг гаргаж чадна.

**Хэн бэлдсэн:** агент (Claude), 2026.11.22. Хэрэглэгч хянаагүй. «Уншсан» төлөвийг зөвхөн `CORE/WEEKLY-PLAN-2026-2027.mn.md`-ийн ✅-ээс авсан; энэ файл хэнийг ч уншсан гэж тэмдэглэхгүй. Машинаар уншигдах хувилбар: `data/reading-plan-20261122.json`.

## Товч дүн

- Нийт **43 өгүүлэл**: уншсан **8**, хэсэгчлэн уншсан **1** (Unimib), уншаагүй **34** (Монгол зургаан ажил орсон).
- Уншаагүй хэсгийн хугацаа **46.5 цаг** + W06-ийн давтлага 1 цаг = **47.5 цаг**.
- Долоо хоногт ойролцоогоор 13 цагаар (1 цаг нөөцтэй) **4 долоо хоног: W05–W08 (11/23–12/20).** W06-д Үзлэг №1 (12/01) тул 10.5 цаг.
- W05–W06-д уншихаар товлосон, Монгол хөтөчгүй байсан дөрвөн өгүүлэлд шинэ хөтөч бэлдсэн: RAG16 (Bruch нар), RAG17 (Joren нар), RAG15 (GraphRAG), RAG07 (ALCE).
- W09-өөс хойш заавал унших шинэ өгүүлэл үлдэхгүй; төлөвлөгөөний долоо хоног бүрт тухайн өгүүллээ 30 минут давтана (§3).

## 1. Арга

### Хаанаас цуглуулсан

- **Дипломын иш татсан бүтээл:** `thesis/Chapters/Chapter1–5` (багшид үзүүлэх ноорог) ба `thesis/Chapters/full/*.tex` (зөвхөн бүтэн ноорог) дахь `\cite`-ийг `thesis/references.bib`-ээр тайлсан; `\iffalse…\fi` доторхыг тооцоогүй. Нийт 23 бүтээл: багшид үзүүлэх ноорогт 14 (9 өгүүлэл, 5 вэб баримт бичиг), зөвхөн бүтэн ноорогт 9 (7 өгүүлэл, 2 баримт бичиг). Вэб баримт бичгийг §5-д тусад нь жагсаав.
- **Төлөвлөгөө:** WEEKLY-PLAN-ийн «Унших дараалал ба төлөв» хүснэгт ба W02–W21-ийн «Унших, ойлгох» мөр бүр.
- **Монгол ажил:** MON01–MON06 (`papers/43-*`).
- **Код, унших хэсэг:** `papers/16-reading-notes-45-20261101.mn.md`, `papers/10-*.json`, `papers/21-reading-list-update-20261104.mn.md`.

### «Уншсан» гэж тооцох дүрэм

WEEKLY-PLAN-д хэрэглэгч өөрөө хэлсэн гэж ✅ тавьсан өгүүлэл л уншсан (2026.11.22-нд `grep "✅"`-ээр шалгасан). Нэг мөрөнд хэд хэдэн өгүүлэл байвал («Matic ✅, Marcel үлдсэн» гэх мэт) өгүүлэл бүрээр нь салгасан.

### Хугацааны томьёо

- Цаг = унших хэсгийн хуудас ÷ хурд + 0.5 цаг (хөтчийн «Өөрийгөө шалгах асуулт» ба 1 хуудасны тэмдэглэл). Хурд: англи өгүүлэл Монгол хөтөчтэй 5 хуудас/цаг, Монгол өгүүлэл 10 хуудас/цаг. Хуудас = зөвхөн унших хэсгүүдийн PDF хуудас (0.5 хуудас руу ойролцоолсон). Цагийг хамгийн ойрын 0.5 цаг руу ойролцоолно (яг дунд нь бол дээш: 1.25 → 1.5).
- Хуудсыг 2026.11.22-нд татсан PDF-ээс `pdfinfo`, `pdftotext`-оор тоолж, хэсгийн гарчгаар хил тогтоосон. Нэг баганатай урт хуудастай (arXiv, ICLR, LNCS) өгүүлэлд хуудас бүр хөнгөн тул цаг нь аюулгүй талдаа.
- Энэ бол таамаг. W05-ын эцэст бодит зарцуулсан цагаа тэмдэглэвэл хурдыг тохируулж болно.

### Дараалал

1. **Багшид амласан, хоцорсон:** SQuAD 2.0 (RAG08) ба Монгол зургаан ажил — 11/17-ны слайдад амласан.
2. **Багшид үзүүлэх ноорогт иш татсан, уншаагүй:** байхгүй — тэнд иш татсан 9 өгүүлэл бүгд ✅ (Unimib-ийн үлдсэн §4-өөс бусад).
3. **Уншлагын хүснэгтэд W03–W04 гэж төлөвлөсөн, бүтэн ноорогт иш татсан, уншаагүй:** Marcel, CLINC150, RAPTOR, Han нар, TaxoIndex, T-RAG. Эдгээрийг уншсаны дараа л бүтэн нооргийн догол мөрийг багшид үзүүлэх ноорог руу зөөнө.
4. **Төлөвлөгөөний ирэх долоо хоногт хэрэгтэй:** тухайн долоо хоногоос өмнө уншина (W07-ийнх W06-д, W11–W20-ийнх W07–W08-д).

## 2. Долоо хоногийн хуваарь

### W05 · 11.23–11.29 — Үзлэг №1-ийн материал бэлдэх (нийт 13 цаг)

Эхлээд багшид амласан SQuAD 2.0 ба Монгол зургаан ажлыг уншина. Төлөвлөгөөний «тоймын бичвэр» (уншсан өгүүллээр ном зохиолын тойм бичих) нь бичих ажил тул энэ цагт тооцоогүй.

| № | Код | Өгүүлэл | Унших хэсэг | Хуудас | Цаг | Хөтөч |
|---|---|---|---|---|---|---|
| 1 | RAG08 | Rajpurkar, Jia, Liang (2018). *Know What You Don't Know: Unanswerable Questions for SQuAD (SQuAD 2.0)* | Бүтнээр (хураангуй – §6). Хүснэгтийн мөрөнд «хураангуй, §1–3», W03-ын мөрөнд «богино тул бүтнээр» гэсэн; бүтэн ноорогт §4.1, §5.2-ын тоо орсон тул бүтнээр. | 5 | 1.5 | [22-RAG08-delgerengui-hotoch-20261104.mn.md](22-RAG08-delgerengui-hotoch-20261104.mn.md) (дэлгэрэнгүй хөтөч) |
| 2 | MON01 | З. Цолмон, Г. Саруул (2022). *Гүн сургалтын арга ашигласан Монгол дохионы хэлний хөрвүүлэгч* | Бүтнээр, хэллэгийг нь анзаарч | 4 | 1 | [43-MON01-dohionii-hel-hotoch-20261120.mn.md](43-MON01-dohionii-hel-hotoch-20261120.mn.md) (хэллэгийн хөтөч) |
| 3 | MON02 | Б. Сувдаа, Н. Баярсайхан, Г. Нандинбилиг (2022). *Уртын дууны төрлийг шүлгийн өгөгдөл ашиглан машин сургалтын аргаар …* | Бүтнээр, хэллэгийг нь анзаарч | 5 | 1 | [43-MON02-urtiin-duu-hotoch-20261120.mn.md](43-MON02-urtiin-duu-hotoch-20261120.mn.md) (хэллэгийн хөтөч) |
| 4 | MON03 | Б. Батням, Ц. Лхамролом, Б. Наранчимэг (2023). *Программ хангамжийн статик загвараас зохиомжийн согогийг илрүүлэх нь* | Бүтнээр, хэллэгийг нь анзаарч | 5 | 1 | [43-MON03-zohiomjiin-sogog-hotoch-20261120.mn.md](43-MON03-zohiomjiin-sogog-hotoch-20261120.mn.md) (хэллэгийн хөтөч) |
| 5 | MON04 | Ц. Сарангэрэл, Б. Нямсүрэн, Г. Дүгэржав, Г. Чулуун-Эрдэнэ (2025). *Эрдэм шинжилгээний хураангуйд хийсэн утга зүй болон үг зүйн шинжилгээ* | Бүтнээр (англи хураангуй, ном зүйгээс бусад), хэллэгийг нь анзаарч | 8 | 1.5 | [43-MON04-huraangui-shinjilgee-hotoch-20261120.mn.md](43-MON04-huraangui-shinjilgee-hotoch-20261120.mn.md) (хэллэгийн хөтөч) |
| 6 | MON05 | О. Мөнхбат (2011). *Эрдэм шинжилгээний бичлэг: нийтлэг шаардлага, загварууд* | Бүтнээр | 3.5 | 1 | [43-MON05-bichleg-shaardlaga-hotoch-20261120.mn.md](43-MON05-bichleg-shaardlaga-hotoch-20261120.mn.md) (хэллэгийн хөтөч) |
| 7 | MON06 | Тана, Т. Баянмөнх, Я. Оюунчулуун, Д. Энхтүвшин, Ч. Энхбат (2023). *Биологийн хичээлийн цахим болон танхимын сургалтын үр дүнг харьцуул…* | Бүтнээр (ном зүй, англи хураангуйгаас бусад), хэллэгийг нь анзаарч | 8.5 | 1.5 | [43-MON06-tsahim-tanhim-hotoch-20261120.mn.md](43-MON06-tsahim-tanhim-hotoch-20261120.mn.md) (хэллэгийн хөтөч) |
| 8 | RAG16 | Bruch, Gai, Ingber (2023). *An Analysis of Fusion Functions for Hybrid Retrieval* | Хураангуй, §1, §3.1, §5 ба §5.1 (Хүснэгт 2–3), §7 | 7.5 | 2 | [47-RAG16-fusion-hotoch-20261122.mn.md](47-RAG16-fusion-hotoch-20261122.mn.md) (шинэ хөтөч, 2026.11.22) |
| 9 | TRE01 · CLINC150 | Larson et al. (2019). *An Evaluation Dataset for Intent Classification and Out-of-Scope Pr…* | Хураангуй, §1, §2.2, §4, §6 | 2.5 | 1 | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) (богино хөтөч, 4 өгүүлэл нэг дор) |
| 10 | CMP01 · Marcel | Trienes et al. (2025). *Marcel: A Lightweight and Open-Source Conversational Agent for Univ…* | Хураангуй, §1, §3 (3.1–3.3), Limitations | 4.5 | 1.5 | [30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md](30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md) (богино хөтөч, §2б) |

### W06 · 11.30–12.06 — Үзлэг №1-д ажлаа үзүүлэх, 12/01 (нийт 10.5 цаг)

12/01-ний Үзлэг №1 тул 10.5 цаг (13 цаг биш). Мягмар гарагаас өмнө 1 цагийн давтлага хийнэ. Шинэ уншлага бүгд бүтэн ноорогт иш татсан мод, графын сэдэв ба W07–W08-д хэрэгтэй хоёр өгүүлэл.

| № | Код | Өгүүлэл | Унших хэсэг | Хуудас | Цаг | Хөтөч |
|---|---|---|---|---|---|---|
| 1 | — | Давтлага (төлөвлөгөөний W06 «Унших, ойлгох»): W02–W05-ын дөрвөн ойлголтыг (RAG, хариугүй асуулт, BM25, RRF) номгүй, 3 минутад тайлбарлах | — | — | 1 | — |
| 2 | RAG14 | Sarthi et al. (2024). *RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval* | Хураангуй, §3, §4.1, Хавсралт E | 5.5 | 1.5 | [29-RAG14-RAPTOR-bogino-hotoch-20261115.mn.md](29-RAG14-RAPTOR-bogino-hotoch-20261115.mn.md) (богино хөтөч) |
| 3 | TRE01 · Han | Han et al. (2025). *RAG vs. GraphRAG: A Systematic Evaluation and Key Insights* | Хураангуй, §1, §3, §4.1–4.4, §7 | 4 | 1.5 | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) (богино хөтөч, 4 өгүүлэл нэг дор) |
| 4 | TRE01 · TaxoIndex | Kang et al. (2024). *Taxonomy-guided Semantic Indexing for Academic Paper Search (TaxoIn…* | Хураангуй, §1, §5.2 (гол хүснэгт), §6–7 | 3 | 1 | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) (богино хөтөч, 4 өгүүлэл нэг дор) |
| 5 | TRE01 · TRAG | Fatehkia, Lucas, Chawla (2024). *T-RAG: Lessons from the LLM Trenches* | Хураангуй, §1, §5.3 (байгууллагын мод), §6.1 (37 асуулт) | 4 | 1.5 | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) (богино хөтөч, 4 өгүүлэл нэг дор) |
| 6 | RAG15 | Edge et al. (2024). *From Local to Global: A GraphRAG Approach to Query-Focused Summariz…* | Хураангуй, §1, Зураг 1 ба §3.1-ийн эхний догол мөр | 1.5 | 1 | [47-RAG15-graphrag-hotoch-20261122.mn.md](47-RAG15-graphrag-hotoch-20261122.mn.md) (шинэ хөтөч, 2026.11.22) |
| 7 | RAG17 | Joren et al. (2025). *Sufficient Context: A New Lens on Retrieval Augmented Generation Sy…* | Хураангуй, §1, §3–3.1 (тодорхойлолт), Хүснэгт 1, §4.2 (Зураг 3), §6 | 4.5 | 1.5 | [47-RAG17-sufficient-context-hotoch-20261122.mn.md](47-RAG17-sufficient-context-hotoch-20261122.mn.md) (шинэ хөтөч, 2026.11.22) |
| 8 | RAG07 | Gao, Yen, Yu, Chen (2023). *Enabling Large Language Models to Generate Text with Citations (ALCE)* | Хураангуй, §1–3 (хэмжүүр), §6 (хүний үнэлгээ), §8, Limitations | 5.5 | 1.5 | [47-RAG07-alce-hotoch-20261122.mn.md](47-RAG07-alce-hotoch-20261122.mn.md) (шинэ хөтөч, 2026.11.22) |

### W07 · 12.07–12.13 — Хайлтын аргуудыг харьцуулах (нийт 12.5 цаг)

Олон богино (4–5 хуудас) Interspeech, arXiv өгүүлэл. W11–W15-д хэрэгтэй уншлагыг урьдчилж уншина.

| № | Код | Өгүүлэл | Унших хэсэг | Хуудас | Цаг | Хөтөч |
|---|---|---|---|---|---|---|
| 1 | RAG18 | Liu, Zhang, Liang (2023). *Evaluating Verifiability in Generative Search Engines* | Хураангуй, §1–2 (хэмжүүр), §3.3 (хүний үнэлгээний журам), §4.2 (гол үр дүн), §6 | 6 | 1.5 | бэлдээгүй |
| 2 | STT21 | Antonova, Bakhturina, Ginsburg (2022). *Thutmose Tagger: Single-pass neural model for Inverse Text Normaliz…* | Бүтнээр (х.1–4): оршил, tagging, алдааны шинжилгээ, орос хэлний үр дүн | 3.5 | 1 | бэлдээгүй |
| 3 | STT17 | Manohar, Pillai, Sherly (2024). *What is lost in Normalization? Exploring Pitfalls in Multilingual A…* | Бүтнээр (х.1–4) | 3.5 | 1 | бэлдээгүй |
| 4 | TTS04 | Gorman, Sproat (2016). *Minimally Supervised Number Normalization* | Хураангуй, §1–2, §3.2, §5–6 (FST-ийн дэлгэрэнгүй §4-ийг алгасна) | 4 | 1.5 | бэлдээгүй |
| 5 | TTS11 | Taylor, Richmond (2021). *Confidence Intervals for ASR-based TTS Evaluation* | Бүтнээр (х.1–4) | 4 | 1.5 | бэлдээгүй |
| 6 | TTS07 | Wolters, Isaac, Renals (2010). *Evaluating Speech Synthesis Intelligibility using Amazon Mechanical…* | Хураангуй, §1, §3, §5–6 | 3.5 | 1 | бэлдээгүй |
| 7 | STT18 | Szymański et al. (2023). *Why Aren't We NER Yet? Artifacts of ASR Errors in Named Entity Reco…* | Хураангуй, §1, §3–4, §6–7 | 5 | 1.5 | бэлдээгүй |
| 8 | RAG03 | Karpukhin et al. (2020). *Dense Passage Retrieval for Open-Domain Question Answering (DPR)* | Хураангуй, §1, §3, §5 | 4 | 1.5 | бэлдээгүй |
| 9 | STT16 | Kim et al. (2021). *Semantic Distance: A New Metric for ASR Performance Analysis Toward…* | Бүтнээр (х.1–4) | 3.5 | 1 | бэлдээгүй |
| 10 | STT19 | Rugayan, Salvi, Svendsen (2023). *Perceptual and Task-Oriented Assessment of a Semantic Metric for AS…* | Бүтнээр (х.1–4) | 3.5 | 1 | бэлдээгүй |

### W08 · 12.14–12.20 — Хариулт сонгох хоёр аргыг харьцуулах (нийт 11.5 цаг)

Үлдсэн бүх заавал унших өгүүлэл энэ долоо хоногт дуусна.

| № | Код | Өгүүлэл | Унших хэсэг | Хуудас | Цаг | Хөтөч |
|---|---|---|---|---|---|---|
| 1 | TTS10 | Luger, Sellen (2016). *"Like Having a Really bad PA": The Gulf between User Expectation an…* | Хураангуй, удиртгал, арга, үр дүн (findings), хэлэлцүүлэг, хязгаар, дүгнэлт (холбоотой ажлыг алгасна) | ~8 | 2 | бэлдээгүй |
| 2 | CMP01 · Unimib | Antico, Giordano, Koyuturk, Ognibene (2024). *Unimib Assistant: Designing a Student-Friendly RAG-Based Chatbot fo…* | Үлдсэн хэсэг: §4 «Limits and future developments» (хураангуй, оршил, үр дүнг 11/16-нд уншсан) | 1.5 | 1 | [30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md](30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md) (богино хөтөч) |
| 3 | RAG13 | Chen, Lin, Han, Sun (2024). *Benchmarking Large Language Models in Retrieval-Augmented Generatio…* | Хураангуй, удиртгал, «Required abilities of RAG», үнэлгээний хэмжүүр, «Negative Rejection»-ий үр дүн, дүгнэлт | 3.5 | 1 | бэлдээгүй |
| 4 | RAG19 | Yu, Gan, Zhang, Tong, Liu, Liu (2024). *Evaluation of Retrieval-Augmented Generation: A Survey* | Хураангуй, §1, §3 (Auepora: 3.1, 3.3-ын хэмжүүрийн хүснэгт), §5 | 10.5 | 2.5 | бэлдээгүй |
| 5 | RAG09 | Es, James, Espinosa-Anke, Schockaert (2024). *RAGAs: Automated Evaluation of Retrieval Augmented Generation* | Хураангуй, §1, §3 (хэмжүүрийн тодорхойлолт) | 2.5 | 1 | бэлдээгүй |
| 6 | TTS12 | Kirkland, Mehta, Lameris, Henter, Székely, Gustafson (2023). *Stuck in the MOS pit: A critical analysis of MOS test methodology i…* | Бүтнээр (х.1–6) | 5 | 1.5 | бэлдээгүй |
| 7 | TTS06 | Chiang, Huang, Lee (2023). *Why We Should Report the Details in Subjective Evaluation of TTS Mo…* | Бүтнээр (х.1–4) | 4 | 1.5 | бэлдээгүй |
| 8 | STT15 | Liu, Peng (2020). *Statistical Testing on ASR Performance via Blockwise Bootstrap* | Хураангуй, §1–2 (арга), §4–6 (туршилт, дүгнэлт); баталгааг алгасна | 3.5 | 1 | бэлдээгүй |

**Үзлэгийн долоо хоногт цаг дутвал:** W05-ын Marcel (1.5) ба CLINC150 (1.0)-ыг W06 руу, W06-ийн ALCE (1.5)-г W07 руу шилжүүлнэ. SQuAD 2.0 ба Монгол зургаан ажлыг 12/01-нээс өмнө дуусгах нь чухал — багшид амласан.

## 3. W09–W20: давтлага (шинэ уншлагагүй)

Төлөвлөгөөний долоо хоног бүрийн «Унших, ойлгох» өгүүллийг тэр долоо хоногт **30 минут** давтана: хөтчийн «Өөрийгөө шалгах асуулт», төлөвлөгөөний «Чадах ёстой»-г номгүй тайлбарлах.

| Долоо хоног | Давтах өгүүлэл |
|---|---|
| W09 | RAG14 RAPTOR, TRE01 Han, RAG15 GraphRAG |
| W11 | STT21 Thutmose, STT17, TTS04 |
| W12 | TTS11 Taylor, TTS07 |
| W13 | STT18, STT22 Sidiropoulos |
| W14 | RAG03 DPR, RAG05 E5 |
| W15 | STT16, STT19 |
| W16 | TTS10 Bad PA, Unimib |
| W17 | RAG13 RGB |
| W18 | RAG19 Yu, RAG09 RAGAS |
| W19 | TTS12 Kirkland, TTS06 Chiang |
| W20 | STT15 |

## 4. Бүрэн жагсаалт

### 4.1 Уншаагүй ба хэсэгчлэн уншсан

| Код | Зохиогч, он, өгүүлэл | Холбоос | PDF х. | Унших х. | Цаг | Долоо хоног | Хаана хэрэгтэй | Хөтөч | Төлөв |
|---|---|---|---|---|---|---|---|---|---|
| RAG08 | Rajpurkar, Jia, Liang (2018). *Know What You Don't Know: Unanswerable Questions for SQuAD (SQuAD 2.0)*. ACL 2018 (богино өгүүлэл) | https://aclanthology.org/P18-2124/ | 6 | 5 | 1.5 | W05 | Бүтэн ноорог 2.1 «Хариулт байхгүй асуулт»; W03 «Унших, ойлгох»; 11/17-ны слайдад «энэ долоо хоногт уншина» гэж амласан | [22-RAG08-delgerengui-hotoch-20261104.mn.md](22-RAG08-delgerengui-hotoch-20261104.mn.md) | уншаагүй |
| MON01 | З. Цолмон, Г. Саруул (2022). *Гүн сургалтын арга ашигласан Монгол дохионы хэлний хөрвүүлэгч*. Mongolian Journal of Engineering and Applied Sciences 4(1) | https://journal.num.edu.mn/EAS/article/view/920 | 5 | 4 | 1 | W05 | 11/17-ны слайдад «Монгол судалгааны ажил унших» гэж амласан (W04); дипломын эрдэм шинжилгээний хэллэг | [43-MON01-dohionii-hel-hotoch-20261120.mn.md](43-MON01-dohionii-hel-hotoch-20261120.mn.md) | уншаагүй |
| MON02 | Б. Сувдаа, Н. Баярсайхан, Г. Нандинбилиг (2022). *Уртын дууны төрлийг шүлгийн өгөгдөл ашиглан машин сургалтын аргаар ангилах нь*. Mongolian Journal of Engineering and Applied Sciences 4(1) | https://journal.num.edu.mn/EAS/article/view/975 | 7 | 5 | 1 | W05 | 11/17-ны слайдад амласан (W04); дипломын хэллэг | [43-MON02-urtiin-duu-hotoch-20261120.mn.md](43-MON02-urtiin-duu-hotoch-20261120.mn.md) | уншаагүй |
| MON03 | Б. Батням, Ц. Лхамролом, Б. Наранчимэг (2023). *Программ хангамжийн статик загвараас зохиомжийн согогийг илрүүлэх нь*. Mongolian Journal of Engineering and Applied Sciences 5(2) | https://journal.num.edu.mn/EAS/article/view/4978 | 7 | 5 | 1 | W05 | 11/17-ны слайдад амласан (W04); дипломын хэллэг | [43-MON03-zohiomjiin-sogog-hotoch-20261120.mn.md](43-MON03-zohiomjiin-sogog-hotoch-20261120.mn.md) | уншаагүй |
| MON04 | Ц. Сарангэрэл, Б. Нямсүрэн, Г. Дүгэржав, Г. Чулуун-Эрдэнэ (2025). *Эрдэм шинжилгээний хураангуйд хийсэн утга зүй болон үг зүйн шинжилгээ*. Mongolian Journal of Humanities and Social Sciences 10(20), х.35–44 | https://www.mongoliajol.info/index.php/MJHSS/article/view/4015 | 10 | 8 | 1.5 | W05 | 11/17-ны слайдад амласан (W04); дипломын хэллэг | [43-MON04-huraangui-shinjilgee-hotoch-20261120.mn.md](43-MON04-huraangui-shinjilgee-hotoch-20261120.mn.md) | уншаагүй |
| MON05 | О. Мөнхбат (2011). *Эрдэм шинжилгээний бичлэг: нийтлэг шаардлага, загварууд*. МУИС-ийн Эрдэм шинжилгээний бичиг №8 (377), Социологи, х.28–31 | https://journal.num.edu.mn/soc/article/view/9782 | 4 | 3.5 | 1 | W05 | 11/17-ны слайдад амласан (W04); эх сурвалжийг иш татах загвар | [43-MON05-bichleg-shaardlaga-hotoch-20261120.mn.md](43-MON05-bichleg-shaardlaga-hotoch-20261120.mn.md) | уншаагүй |
| MON06 | Тана, Т. Баянмөнх, Я. Оюунчулуун, Д. Энхтүвшин, Ч. Энхбат (2023). *Биологийн хичээлийн цахим болон танхимын сургалтын үр дүнг харьцуулсан судалгаа*. Lavai – International Journal of Education 19(29), х.2–14 | https://www.mongoliajol.info/index.php/Lavai/article/view/3206 | 13 | 8.5 | 1.5 | W05 | 11/17-ны слайдад амласан (W04); дипломын хэллэг | [43-MON06-tsahim-tanhim-hotoch-20261120.mn.md](43-MON06-tsahim-tanhim-hotoch-20261120.mn.md) | уншаагүй |
| RAG16 | Bruch, Gai, Ingber (2023). *An Analysis of Fusion Functions for Hybrid Retrieval*. ACM TOIS (DOI 10.1145/3596512); arXiv 2210.11934v2 | https://arxiv.org/abs/2210.11934 | 36 | 7.5 | 2 | W05 | W05 «Унших, ойлгох» (RRF, k=60 ба манай k=30); W07 хайлтын харьцуулалт | [47-RAG16-fusion-hotoch-20261122.mn.md](47-RAG16-fusion-hotoch-20261122.mn.md) | уншаагүй |
| TRE01 · CLINC150 | Larson et al. (2019). *An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction (CLINC150)*. EMNLP-IJCNLP 2019 | https://aclanthology.org/D19-1131/ | 6 | 2.5 | 1 | W05 | Бүтэн ноорог 2.1 «Хариулт байхгүй асуулт»; уншлагын хүснэгтийн TRE01 мөр (W03–W04) | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) | уншаагүй |
| CMP01 · Marcel | Trienes et al. (2025). *Marcel: A Lightweight and Open-Source Conversational Agent for University Student Support*. arXiv 2507.13937v2 | https://arxiv.org/abs/2507.13937 | 15 | 4.5 | 1.5 | W05 | Бүтэн ноорог 2.1 (Marcel-ийн жишээ) ба «Хариулт байхгүй асуулт»; CMP01 мөр (W03–W04) | [30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md](30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md) | уншаагүй |
| RAG14 | Sarthi et al. (2024). *RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval*. ICLR 2024 | https://arxiv.org/abs/2401.18059 | 23 | 5.5 | 1.5 | W06 | Бүтэн ноорог 2.2 «Мэдлэгийн мод дээрх хайлт»; W09 «Унших, ойлгох»; RAG14 мөр (W03–W04) | [29-RAG14-RAPTOR-bogino-hotoch-20261115.mn.md](29-RAG14-RAPTOR-bogino-hotoch-20261115.mn.md) | уншаагүй |
| TRE01 · Han | Han et al. (2025). *RAG vs. GraphRAG: A Systematic Evaluation and Key Insights*. KDD '26; arXiv 2502.11371 | https://arxiv.org/abs/2502.11371 | 12 | 4 | 1.5 | W06 | Бүтэн ноорог 2.2; W09 (модтой ба модгүй хайлтыг харьцуулах зарчим); TRE01 мөр | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) | уншаагүй |
| TRE01 · TaxoIndex | Kang et al. (2024). *Taxonomy-guided Semantic Indexing for Academic Paper Search (TaxoIndex)*. EMNLP 2024; arXiv 2410.19218 | https://arxiv.org/abs/2410.19218 | 16 | 3 | 1 | W06 | Бүтэн ноорог 2.2; TRE01 мөр | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) | уншаагүй |
| TRE01 · TRAG | Fatehkia, Lucas, Chawla (2024). *T-RAG: Lessons from the LLM Trenches*. arXiv 2402.07483 (хянан магадлагаагүй) | https://arxiv.org/abs/2402.07483 | 22 | 4 | 1.5 | W06 | Бүтэн ноорог 2.2 (37 асуултын 27 ба 21); TRE01 мөр | [32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md](32-TRE01-mod-chigluuleh-bogino-hotoch-20261115.mn.md) | уншаагүй |
| RAG15 | Edge et al. (2024). *From Local to Global: A GraphRAG Approach to Query-Focused Summarization*. arXiv 2404.16130v2 (preprint) | https://arxiv.org/abs/2404.16130 | 26 | 1.5 | 1 | W06 | W09 «Унших, ойлгох» (мэдлэгийн мод GraphRAG биш гэдгийг тайлбарлах) | [47-RAG15-graphrag-hotoch-20261122.mn.md](47-RAG15-graphrag-hotoch-20261122.mn.md) | уншаагүй |
| RAG17 | Joren et al. (2025). *Sufficient Context: A New Lens on Retrieval Augmented Generation Systems*. ICLR 2025; arXiv 2411.06037v3 | https://arxiv.org/abs/2411.06037 | 25 | 4.5 | 1.5 | W06 | W07 (түгжсэн харьцуулалтын өмнө); W08; W17 LLM ашиглах эсэх | [47-RAG17-sufficient-context-hotoch-20261122.mn.md](47-RAG17-sufficient-context-hotoch-20261122.mn.md) | уншаагүй |
| RAG07 | Gao, Yen, Yu, Chen (2023). *Enabling Large Language Models to Generate Text with Citations (ALCE)*. EMNLP 2023 | https://aclanthology.org/2023.emnlp-main.398/ | 24 | 5.5 | 1.5 | W06 | W08 «Унших, ойлгох» (эшлэл байх нь зөв хариулт гэсэн үг биш) | [47-RAG07-alce-hotoch-20261122.mn.md](47-RAG07-alce-hotoch-20261122.mn.md) | уншаагүй |
| RAG18 | Liu, Zhang, Liang (2023). *Evaluating Verifiability in Generative Search Engines*. arXiv 2304.09848v2 (Findings of EMNLP 2023 гэж иш татдаг, баталгаажаагүй) | https://arxiv.org/abs/2304.09848 | 25 | 6 | 1.5 | W07 | W08 (дүрэм ба LLM-ийн харьцуулалт, хүний үнэлгээ) | бэлдээгүй | уншаагүй |
| STT21 | Antonova, Bakhturina, Ginsburg (2022). *Thutmose Tagger: Single-pass neural model for Inverse Text Normalization*. arXiv 2208.00064 (Interspeech 2022 гэж таамагласан) | https://arxiv.org/abs/2208.00064 | 5 | 3.5 | 1 | W07 | W11 (он, тоо, өрөөний дугаарыг уншуулах) | бэлдээгүй | уншаагүй |
| STT17 | Manohar, Pillai, Sherly (2024). *What is lost in Normalization? Exploring Pitfalls in Multilingual ASR Model Evaluations*. arXiv 2409.02449v4 | https://arxiv.org/abs/2409.02449 | 6 | 3.5 | 1 | W07 | W11 (тоо, оныг хэвийн болгоход WER яаж өөрчлөгдөх) | бэлдээгүй | уншаагүй |
| TTS04 | Gorman, Sproat (2016). *Minimally Supervised Number Normalization*. TACL 4 | https://aclanthology.org/Q16-1036/ | 14 | 4 | 1.5 | W07 | W11 «Унших, ойлгох» | бэлдээгүй | уншаагүй |
| TTS11 | Taylor, Richmond (2021). *Confidence Intervals for ASR-based TTS Evaluation*. Interspeech 2021, х.2791–2795 | https://www.isca-archive.org/interspeech_2021/taylor21_interspeech.html | 5 | 4 | 1.5 | W07 | W12 (Edge TTS-ийн ойлгомжийг ASR-аар шалгах) | бэлдээгүй | уншаагүй |
| TTS07 | Wolters, Isaac, Renals (2010). *Evaluating Speech Synthesis Intelligibility using Amazon Mechanical Turk*. SSW-7 | https://www.isca-archive.org/ssw_2010/wolters10_ssw.pdf | 6 | 3.5 | 1 | W07 | W12 «Унших, ойлгох» | бэлдээгүй | уншаагүй |
| STT18 | Szymański et al. (2023). *Why Aren't We NER Yet? Artifacts of ASR Errors in Named Entity Recognition in Spontaneous Speech Transcripts*. ACL 2023 | https://aclanthology.org/2023.acl-long.98/ | 16 | 5 | 1.5 | W07 | W13 (нэр, тооны алдаа хайлтыг эвдэх) | бэлдээгүй | уншаагүй |
| RAG03 | Karpukhin et al. (2020). *Dense Passage Retrieval for Open-Domain Question Answering (DPR)*. EMNLP 2020 | https://aclanthology.org/2020.emnlp-main.550/ | 13 | 4 | 1.5 | W07 | W14 «Унших, ойлгох» (вектор хайлтын үндэс; RAG01-ийн хайгч) | бэлдээгүй | уншаагүй |
| STT16 | Kim et al. (2021). *Semantic Distance: A New Metric for ASR Performance Analysis Towards Spoken Language Understanding*. arXiv 2104.02138 (Interspeech 2021) | https://arxiv.org/abs/2104.02138 | 5 | 3.5 | 1 | W07 | W15 (WER ижил ч утга өөр) | бэлдээгүй | уншаагүй |
| STT19 | Rugayan, Salvi, Svendsen (2023). *Perceptual and Task-Oriented Assessment of a Semantic Metric for ASR Evaluation*. Interspeech 2023 | https://www.isca-archive.org/interspeech_2023/rugayan23_interspeech.pdf | 5 | 3.5 | 1 | W07 | W15 «Унших, ойлгох» | бэлдээгүй | уншаагүй |
| TTS10 | Luger, Sellen (2016). *"Like Having a Really bad PA": The Gulf between User Expectation and Experience of Conversational Agents*. CHI 2016 | https://www.microsoft.com/en-us/research/wp-content/uploads/2016/08/p5286-luger.pdf | 12 | ~8 | 2 | W08 | W16 «Унших, ойлгох» (дуут туслахад хүн юу хүлээдэг) | бэлдээгүй | уншаагүй |
| CMP01 · Unimib | Antico, Giordano, Koyuturk, Ognibene (2024). *Unimib Assistant: Designing a Student-Friendly RAG-Based Chatbot for All Their Needs*. AIxHMI 2024 (CEUR); arXiv 2411.19554 | https://arxiv.org/abs/2411.19554 | 12 | 1.5 | 1 | W08 | Багшид үзүүлэх ноорог 1.1, 2.4; W16 мөр («Хэрэглэгчийн хүлээлт + Unimib») | [30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md](30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md) | хэсэгчлэн |
| RAG13 | Chen, Lin, Han, Sun (2024). *Benchmarking Large Language Models in Retrieval-Augmented Generation (RGB)*. AAAI 2024; arXiv 2309.01431 | https://arxiv.org/abs/2309.01431 | 9 | 3.5 | 1 | W08 | W17 «Унших, ойлгох» (LLM ашиглах эсэх) | бэлдээгүй | уншаагүй |
| RAG19 | Yu, Gan, Zhang, Tong, Liu, Liu (2024). *Evaluation of Retrieval-Augmented Generation: A Survey*. arXiv 2405.07437v2 (Springer бүлэг) | https://arxiv.org/abs/2405.07437 | 21 | 10.5 | 2.5 | W08 | W18 (дипломын үнэлгээний бүлгийн бүтэц) | бэлдээгүй | уншаагүй |
| RAG09 | Es, James, Espinosa-Anke, Schockaert (2024). *RAGAs: Automated Evaluation of Retrieval Augmented Generation*. EACL 2024 (демо) | https://aclanthology.org/2024.eacl-demo.16/ | 9 | 2.5 | 1 | W08 | W18 «Унших, ойлгох» | бэлдээгүй | уншаагүй |
| TTS12 | Kirkland, Mehta, Lameris, Henter, Székely, Gustafson (2023). *Stuck in the MOS pit: A critical analysis of MOS test methodology in TTS evaluation*. SSW 2023, х.41–47 | https://www.isca-archive.org/ssw_2023/kirkland23_ssw.html | 7 | 5 | 1.5 | W08 | W19 (TTS-ийг хүнээр үнэлэх) | бэлдээгүй | уншаагүй |
| TTS06 | Chiang, Huang, Lee (2023). *Why We Should Report the Details in Subjective Evaluation of TTS More Rigorously*. Interspeech 2023 | https://www.isca-archive.org/interspeech_2023/chiang23_interspeech.pdf | 5 | 4 | 1.5 | W08 | W19 «Унших, ойлгох» | бэлдээгүй | уншаагүй |
| STT15 | Liu, Peng (2020). *Statistical Testing on ASR Performance via Blockwise Bootstrap*. arXiv 1912.09508v2 (Interspeech 2020) | https://arxiv.org/abs/1912.09508 | 6 | 3.5 | 1 | W08 | W20 «Унших, ойлгох» (цөөн хэлэгчээс дүгнэх) | бэлдээгүй | уншаагүй |

### 4.2 Уншсан (WEEKLY-PLAN-д ✅)

| Код | Зохиогч, он, өгүүлэл | Холбоос | PDF х. | Уншсан хэсэг | Хэзээ хэлсэн | Хаана иш татсан | Хөтөч, тэмдэглэл |
|---|---|---|---|---|---|---|---|
| STT01 | Radford et al. (2023). *Robust Speech Recognition via Large-Scale Weak Supervision (Whisper)*. ICML 2023; arXiv 2212.04356 | https://arxiv.org/abs/2212.04356 | 28 | Гол хэсэг | ✅ 11/02 хэрэглэгч уншсан | Багшид үзүүлэх ноорог 1.1, 2.3 | тэмдэглэл: papers/01-whisper-reading.mn.md |
| STT08 | Mengke, Meng, Mihajlik (2025). *Transliteration-Aided Transfer Learning for Low-Resource ASR: A Case Study on Khalkha Mongolian*. Electronics 14(6):1137 | https://doi.org/10.3390/electronics14061137 | — | Гол хэсэг | ✅ 11/02 хэрэглэгч уншсан | Багшид үзүүлэх ноорог 1.1, 2.3 | тэмдэглэл: papers/02-khalkha-transfer-method-notes.mn.md |
| RAG01 | Lewis et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 2020; arXiv 2005.11401 | https://arxiv.org/abs/2005.11401 | 19 | Хураангуй, 1, 2, 4.1, 4.5, 6 | ✅ 11/07 хэрэглэгч уншсан | Багшид үзүүлэх ноорог 1.1, 2.1 | [20-RAG01-delgerengui-hotoch-20261104.mn.md](20-RAG01-delgerengui-hotoch-20261104.mn.md) |
| RAG02 | Robertson, Zaragoza (2009). *The Probabilistic Relevance Framework: BM25 and Beyond*. Foundations and Trends in IR 3(4) | https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf | 59 | 1, 2, 3.1, 3.4, 3.5 | ✅ 11/16 хэрэглэгч: багшид үзүүлсэн нооргт иш татсан бүх ажлыг уншсан | Багшид үзүүлэх ноорог 2.1, 3.4.2 | [23-RAG02-delgerengui-hotoch-20261105.mn.md](23-RAG02-delgerengui-hotoch-20261105.mn.md) |
| RAG12 | Cormack, Clarke, Büttcher (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*. SIGIR 2009 | https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf | 2 | Бүтнээр | ✅ 11/16 хэрэглэгч (иш татсан бүх ажил) | Багшид үзүүлэх ноорог 2.1, 3.4.2 | — |
| RAG05 | Wang et al. (2024). *Multilingual E5 Text Embeddings: A Technical Report*. arXiv 2402.05672 | https://arxiv.org/abs/2402.05672 | 6 | Богино тайлан | ✅ 11/16 хэрэглэгч (иш татсан бүх ажил) | Багшид үзүүлэх ноорог 2.1, 3.4.2; W07, W14 «Унших, ойлгох» | — |
| STT22 | Sidiropoulos, Vakulenko, Kanoulas (2022). *On the Impact of Speech Recognition Errors in Passage Retrieval for Spoken Question Answering*. CIKM 2022; arXiv 2209.12944 | https://arxiv.org/abs/2209.12944 | 6 | Оршил, §3, BM25 ба вектор хайлтын үр дүн | ✅ 11/16 хэрэглэгч (иш татсан бүх ажил) | Багшид үзүүлэх ноорог 2.3; W13 | — |
| CMP01 · Burch | Matic, Zajmovic (2026). *Design and Implementation of a Retrieval-Augmented Chatbot for the International Burch University Website*. INFOTEH-JAHORINA 2026 (оюутны өгүүлэл) | https://infoteh.etf.ues.rs.ba/zbornik/2026/radovi/306.pdf | 6 | Хураангуй, оршил, үр дүн | ✅ 11/16 хэрэглэгч (иш татсан бүх ажил) | Багшид үзүүлэх ноорог 1.1, 2.4 | [30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md](30-CMP01-surguuliin-tuslah-bogino-hotoch-20261115.mn.md) |

Unimib-ийг хоёр газар бүртгэсэн: CMP01 мөрөнд ✅ (хураангуй, оршил, үр дүн, 11/16), W16 мөрөнд «Үлдсэн». Иймд «хэсэгчлэн» гэж тооцож, үлдсэн §4-ийг W08-д товлосон.

## 5. Дипломд иш татсан вэб баримт бичиг (өгүүлэл биш, цагт тооцоогүй)

Иш татсан өгүүлбэрээ тухайн хуудастай нэг удаа тулгахад 10–15 минут хангалттай.

| Bib түлхүүр | Баримт бичиг | Хаана | Холбоос |
|---|---|---|---|
| `cafet_whisper_small_mn` | Cafet — whisper-small-mongolian (Hugging Face загварын хуудас) | Багшид үзүүлэх ноорог 2.3 | https://huggingface.co/Cafet/whisper-small-mongolian |
| `google_transcribe_model` | Google — Gemini 3.5 Transcribe (Gemini API-ийн баримт бичиг) | Багшид үзүүлэх ноорог 2.3 | https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe |
| `google_pricing` | Google — Gemini Developer API pricing | Багшид үзүүлэх ноорог 2.3 | https://ai.google.dev/gemini-api/docs/pricing |
| `openai_whisper_repo` | OpenAI — Whisper README (загвар ба хэлний жагсаалт) | Багшид үзүүлэх ноорог 2.3 | https://github.com/openai/whisper |
| `edge_tts` | rany2 — edge-tts (Python сан, хувилбар 7.3.1) | Багшид үзүүлэх ноорог 3.5 | https://github.com/rany2/edge-tts |
| `google_rate_limits` | Google — Gemini API rate limits | Бүтэн ноорог 2.3 | https://ai.google.dev/gemini-api/docs/rate-limits |
| `google_terms` | Google — Gemini API Additional Terms of Service | Бүтэн ноорог 2.3 | https://ai.google.dev/gemini-api/terms |

## 6. Сонголтот (хуваарьт оруулаагүй)

| Өгүүлэл | Холбоос | Хэзээ хэрэгтэй |
|---|---|---|
| Gao нар — Retrieval-Augmented Generation for Large Language Models: A Survey | https://arxiv.org/abs/2312.10997 | RAG01 хэцүү санагдвал §II, §III, §VI |
| Sun нар (2023) — нэрийг хэлний загвараар засах (contextual biasing) | https://arxiv.org/abs/2309.00723 | Gemini-ийн үгийн жагсаалттай ойр |
| Qu, Tu, Bao — chunking (Findings of NAACL 2025) | https://aclanthology.org/2025.findings-naacl.114 | Хэсэглэх аргыг өөрчлөх үед |
| MMTEB; BGE-M3 | https://arxiv.org/abs/2502.13595 | Embedding загвар солих үед л (https://arxiv.org/abs/2402.03216) |
| Wen нар — татгалзлын тойм; Gan нар 2025 — RAG үнэлгээний тойм | https://arxiv.org/abs/2407.18418 | Лавлах материал (https://arxiv.org/abs/2504.14891) |
| HippoRAG | https://arxiv.org/abs/2405.14831 | Том граф, олон алхамтай асуулт |
| Nguyen-Duc нар 2025 — их сургуулийн туслах | https://arxiv.org/abs/2507.11272 | Төсөөтэй систем (2.4) |
| Cooper нар 2025; MnTTS; Bao 2026 | https://arxiv.org/abs/2503.03250 | Дуу үүсгэх тал (https://arxiv.org/abs/2209.10848, https://arxiv.org/abs/2608.22872) |
| RAG06 Lost in the Middle; RAG04 BEIR; RAG11 MIRACL | https://aclanthology.org/2024.tacl-1.9/ | Хуучин 45-ын жагсаалтаас сонголтот болсон |
| ALOHA (Tao нар, 2025) | https://arxiv.org/abs/2505.08130 | Бүтэн нооргийн \iffalse-ээр унтраасан 2.4-т л иш татсан |
| Asura-lab/diplom ба бусад Монгол диплом (papers/28, papers/36) | https://github.com/Asura-lab/diplom | 11/16-нд «бусад Монгол дипломыг хараахан уншаагүй» гэсэн; 11/20-нд унших зургаан Монгол ажлыг MON01–MON06 болгон сонгосон |

## 7. Хязгаар ба нэгтгэхэд анхаарах зүйл

- Хуудасны тоо 2026.11.22-нд татсан PDF-ээс. STT08-ийн MDPI хуудас (403) нээгдээгүй тул хуудсыг тоолоогүй (уншсан тул хуваарьт нөлөөгүй). RAG13-ыг arXiv v2-оор (9 х.) тоолсон (AAAI-ийн PDF өмнө нь автомат уншлагад «Access Denied» өгсөн, papers/16). TTS10-ийн хэсгийн хил PDF-ийн текстэд тод биш тул 8 хуудсыг ойролцоогоор авсан.
- Төлөвлөгөөний зөрүү: (1) SQuAD 2.0 — хүснэгтэд «хураангуй, §1–3», W03-ын мөрөнд «бүтнээр»; бүтэн ноорогт §4.1, §5.2-ын тоо орсон тул бүтнээр сонгов. (2) Unimib — дээрх §4.2-ын тайлбар. (3) W06-ийн мөрөнд «шинэ өгүүлэлгүй» гэсэн ч хэрэглэгчийн шинэ 14 цагийн хүсэлтээр W06-д шинэ уншлага орсон; төлөвлөгөөний давтлагыг 1 цагаар хадгалав.
- **Шинэ код (санал):** RAG16 Bruch нар, RAG17 Joren нар, RAG18 Liu нар, RAG19 Yu нар, STT21 Thutmose, STT22 Sidiropoulos нар, TTS11 Taylor, Richmond, TTS12 Kirkland нар. Ашиглагдаагүй эсэхийг `papers/`, `CORE/`, `data/`, `config/`, кодонд хайж шалгасан.
- **/reader:** `reading_room.py` хөтчийг `papers/*<КОД>*hotoch*.md`-ээр олж, уншлагын хүснэгтийн **мөр бүрээс нэг** хөтөч (мөрийн текстэд хамгийн түрүүнд гарсан, хөтөчтэй код) холбоно. Тиймээс W05-ын мөрөнд «RAG16», W07-ийн мөрөнд «RAG17» гэсэн код нэмэх хэрэгтэй; W09-ийн мөрөнд RAG14 ба RAG15 хоёулаа байгаа тул зөвхөн RAG14 холбогдоно — нэг мөрөнд нэг өгүүлэл болговол бүгд холбогдоно.
- CMP01, TRE01 нь хэд хэдэн өгүүллийг нэг дор тайлбарласан богино хөтөч. Энэ хуваарь Marcel, Han нар, T-RAG-ийн унших хэсгийг тэр хөтчөөс өргөн авсан.
- W07–W08-ийн 17 өгүүлэлд Монгол хөтөч алга (RAG18, STT21, STT17, TTS04, TTS11, TTS07, STT18, RAG03, STT16, STT19, TTS10, RAG13, RAG19, RAG09, TTS12, TTS06, STT15). WEEKLY-PLAN-ий W04-ийн тэмдэглэлд Claude-ийн захиалга 12-р сарын эхээр дуусна гэсэн тул эдгээрийг тэрнээс өмнө бэлдэх нь зүйтэй.
- Энэ файл WEEKLY-PLAN-ийг өөрчлөөгүй; төлөвлөгөөнд нэгтгэх, /reader-т холбохыг үндсэн агент хийнэ.
