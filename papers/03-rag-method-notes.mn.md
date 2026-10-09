# RAG — төслийн аргын холбоо, 2026.10.10

Эх: Patrick Lewis et al., Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks. [arXiv2005.11401v4](https://arxiv.org/html/2005.11401v4). Abstract, §1, §2.1–2.4, §4.5 retrieval ablations/index hot-swapping хэсгийн текстийг нягталсан. Бүх хавсралт/benchmark-ийг дахин туршаагүй; хэрэглэгч уншиж дууссан гэж бүртгэхгүй.

Арга нь pretrained DPR retriever ба BART generator-ийг баримтын индекстэй холбож, өөрсдийн туршилтад end-to-end fine-tuning хийсэн. «RAG гэдэг нь ерөөсөө model training байхгүй» гэж энэ өгүүллийг тайлбарлахгүй. Манай баталсан scope-д pretrained component inference ба сургуулийн эхийг олох урсгал хэрэглэнэ; өгүүллийн сургалтын жорыг хуулж хэрэгжүүлэхээр шийдээгүй.

Төслийн дүгнэлт: мэдээллээ source/fact/FAQ дотор хадгалах болон neural model-ийн жинг сургах хоёр тусдаа. Сургуулийн шинэ төлбөр/хаяг оруулахдаа эх ба хүчинтэй хугацаа шинэчлэгдэнэ; STT-г дахин сургах шаардлага гэж үзэхгүй. Энэ бол манай design decision, өгүүллээс бүхэлд нь батлагдсан сургуулийн системийн чанар биш.

Эцсийн roadmap-ийн дагуу A/B-д эхтэй шууд хариу, C шаардлагатай жишээнд генераци, D/E-д тодруулга/татгалзалт бэлтгэнэ. RAG өөрөө бүх хариулт үнэн гэсэн баталгаа биш. Retrieval, router, answer correctness/source support-ийг тусад нь хэмжинэ. Одоогийн 5FAQ draft нь school-approved gold биш; шинэ RAG/LLM ажилласан гэж тайлагнахгүй.
