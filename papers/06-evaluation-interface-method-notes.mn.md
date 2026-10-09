# Эшлэл, хариултын үнэлгээ, дууны интерфэйс — 2026.10.10

[ALCE](https://aclanthology.org/2023.emnlp-main.398.pdf) §3.2/3.3-аас answer correctness, citation recall, citation precision тусдаа гэдгийг нягталсан. Автомат хэмжилтэд NLI зэрэг туслах model ашигладаг. Манайд холбоос байгаагаар claim үнэн гэж оноо өгөхгүй; хүний rubric-аар claim/эхийн дэмжлэг бүртгэх ноорог бэлтгэсэн. ALCE-ийн бүтэн benchmark/model туршилтыг давтаагүй; Монгол NLI suitability батлагдаагүй.

[RAGAs](https://aclanthology.org/2024.eacl-demo.16.pdf) §3 ба judge-ийн хязгаарлалтын хэсэг: faithfulness, answer relevance, context relevance ялгана. Эх туршилтад LLM judge ашигласан; өөрийн judge/prompt-ийн чадвар/тогтворын хамааралтай. Бид эдгээр хэмжилтийн ялгааг rubric-д хэрэглэж, RAGAs API/LLM judge-г эцсийн gold болгон ажиллуулаагүй. Монгол/сургуулийн query дээр human validation шаардлагатай.

[Human-AI Interaction](https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf) Хүснэгт 1-ийн G1/G2/G9/G10, validation summary нягталсан. Чадвар/алдааг ойлгомжтой харуулах, алдаатай гаралтыг засах боломж нь дууны UI-д хэрэгтэй. Манай roadmap-ийн transcript засвар, session reset, дуу тоглуулах/микрофон удирдах хэсэгтэй холбосон. Энэ нь өөрийн kiosk user study хийсэн гэсэн тайлан биш.

[Luger/Sellen2016](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/08/p5286-luger.pdf)-ийн abstract/интервью судалгааны асуудлыг эхний шатанд шалгасан: хэрэглэгчийн хүлээлт, conversational agent-ийн бодит чадвар зөрч болно. Бүх findings-ийг гүн уншаагүй. Манай user task success ба алдаа засах үйлдлийг model metric-ээс тусад нь хэмжих үндэслэл.

Нэгдсэн design decision: STT transcript, retrieved source, route, answer claims/citations, TTS ба user task-ийн тусдаа лог. Одоогийн хөгжүүлэлтийн жижиг score, generated файл, source link-ийг хэрэглэгчийн амжилттай адилтгахгүй.
