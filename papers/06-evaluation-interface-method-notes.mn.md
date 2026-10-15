# Эшлэл, хариултын үнэлгээ, дууны интерфэйс — 2026.10.10

[ALCE](https://aclanthology.org/2023.emnlp-main.398.pdf) §3.2/3.3-аас answer correctness, citation recall, citation precision тусдаа гэдгийг нягталсан. Автомат хэмжилтэд NLI зэрэг туслах model ашигладаг. Манайд холбоос байгаагаар claim үнэн гэж оноо өгөхгүй; хүний rubric-аар claim/эхийн дэмжлэг бүртгэх ноорог бэлтгэсэн. ALCE-ийн бүтэн benchmark/model туршилтыг давтаагүй; Монгол NLI suitability батлагдаагүй.

[RAGAs](https://aclanthology.org/2024.eacl-demo.16.pdf) §3 ба judge-ийн хязгаарлалтын хэсэг: faithfulness, answer relevance, context relevance ялгана. Эх туршилтад LLM judge ашигласан; өөрийн judge/prompt-ийн чадвар/тогтворын хамааралтай. Бид эдгээр хэмжилтийн ялгааг rubric-д хэрэглэж, RAGAs API/LLM judge-г эцсийн gold болгон ажиллуулаагүй. Монгол/сургуулийн query дээр human validation шаардлагатай.

[Human-AI Interaction](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf) Хүснэгт 1-ийн G1/G2/G9/G10, validation summary нягталсан. Чадвар/алдааг ойлгомжтой харуулах, алдаатай гаралтыг засах боломж нь дууны UI-д хэрэгтэй. Манай roadmap-ийн transcript засвар, session reset, дуу тоглуулах/микрофон удирдах хэсэгтэй холбосон. Энэ нь өөрийн kiosk user study хийсэн гэсэн тайлан биш.

[Luger/Sellen2016](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/08/p5286-luger.pdf)-ийн abstract/интервью судалгааны асуудлыг эхний шатанд шалгасан: хэрэглэгчийн хүлээлт, conversational agent-ийн бодит чадвар зөрч болно. Бүх findings-ийг гүн уншаагүй. Манай user task success ба алдаа засах үйлдлийг model metric-ээс тусад нь хэмжих үндэслэл.

Нэгдсэн design decision: STT transcript, retrieved source, route, answer claims/citations, TTS ба user task-ийн тусдаа лог. Одоогийн хөгжүүлэлтийн жижиг score, generated файл, source link-ийг хэрэглэгчийн амжилттай адилтгахгүй.

## 2026.10.15 — эхийн хэсэг, хамаарал, бүрэн байдлын нэмэлт уншлага

Энэ удаа [ALCE, §3.3 «Citation Quality», §3.4 «ALCE is Robust to Shortcut Cases», §6 «Human Evaluation»](https://aclanthology.org/2023.emnlp-main.398.pdf) хэсгийг нягталсан. Citation recall нь хариултын мэдэгдлийг өгсөн эхүүд бүрэн дэмжсэн эсэх, precision нь хамааралгүй эшлэлийг ялгана. Хүний үнэлгээ хариултын utility-г эшлэлийн дэмжлэгээс тусад нь шалгадаг. §3.4-т олдсон эхний хэсгийг өөрийг нь эшлэн буцаахад citation оноо өндөр ч урт хэсгийн найруулга эсвэл эхний хоёр өгүүлбэрийн асуултыг бүрэн хамрах чанар муу байж болохыг үзүүлсэн.

Манай төслийн инженерийн дүгнэлт: эхийн яг хэсгийг сонгон хариулахыг зөвшөөрч болно; гэхдээ citation support, асуултад хамаарал, required facts-ийн бүрэн байдлыг тусад нь шалгана. Хавсаргасан эшлэлд хариулт байгааг үндсэн хариултад дутуу талбарыг автоматаар нөхсөн гэж үзэхгүй. Тоо, объект, нэгж, хугацаа, per-program/total хүрээ болон төлөвлөсөн/үргэлжилж буй/дууссан хэлбэрийг хадгална. ALCE нь манай selector-ийн зөв байдлыг өөрөө баталсан туршилт биш.

[ARES, §3.2 «Preparing LLM Judges», §3.3 «Ranking RAG Systems with Confidence Intervals», §7 «Limitations»](https://aclanthology.org/2024.naacl-long.20.pdf) хэсгийг нягталсан. Олдсон контекстийн хамаарал, хариулт эхдээ үнэнч эсэх, хариулт асуултад хамаатай эсэхийг тусад нь үнэлдэг. Автомат judge-ийн дан дүнд алдаа байж болох тул өөрсдийн PPI үнэлгээнд хүний annotation ашигладаг. Хязгаарлалтад домэйныг мэддэг хүн хэрэгтэй, судалсан өгөгдөл англи хэл дээр байсныг тэмдэглэсэн.

Төслийн шинэ diagnostic кейсүүд AI-authored, human-unreviewed хэвээр: AI дүн assistant_review-д, хүний бодит шалгалт хийгдэх хүртэл human_review=null, human_reference_review=false байна. Дээрх өгүүллийн annotation тоо нь манай шинэ gate биш. Жижиг Монгол AI багцыг ARES-ийн статистикийн баталгаа, human accuracy, эсвэл ALCE/ARES benchmark-ийг бүтнээр давтсан дүн гэж нэрлэхгүй. Эдгээр нь туслахын сонгосон хэсгийн уншлага; хоёр өгүүлэл болон нийт 26 өгүүллийг бүтнээр уншсан, хэрэглэгчийн уншлага дууссан гэсэн тэмдэглэл биш.
