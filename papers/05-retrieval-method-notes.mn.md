# BM25, E5 ба локал туршилтын холбоо — 2026.10.10

[Robertson/Zaragoza2009 зохиогчийн PDF](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) §3.4-ийн saturation ба уртаар хэвийнжүүлэх хэсгийг нягталсан. Термин дахин давтагдах нь оноог хязгааргүй шугаман өсгөхгүй; баримтын урт мөн нөлөөлнө. Манай baseline k1=1.5,b=0.75 ба эерэг log1p IDF ашигладаг; өгүүллийн бүх PRF/BM25F жорыг давтаагүй. Монгол залгавар/alias/stemming хэрэгжээгүй тул lexical coverage хязгаартай.

[Multilingual E5](https://arxiv.org/html/2402.05672v1) §2,§3,Хүснэгт 4/6,AppendixA ба [pinned small card](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3) usage-ийг нягталсан. Эх судалгаа contrastive pretraining ба labeled fine-tuning хийсэн. Бид тэдний бэлэн small жинг inference-д хэрэглэсэн. Query/passages prefix, mask-aware pooling, L2 normalization-ийг card-ийн дагуу ашигласан. MIRACL eval хэлний хүснэгтэд Монгол байхгүй; олон хэлтэй нэрээс Монгол чанарыг шууд дүгнэхгүй.

[BEIR](https://arxiv.org/abs/2104.08663)-ийн abstract нь BM25-ийг бат бөх baseline, зарим хүчтэй аргыг өндөр compute өртөгтэй гэж тайлагнадаг. Манай шийдвэр бол lexical ба dense аргыг ижил corpus/query/qrel дээр бодитоор шалгах. BEIR бүх хүснэгт/split-ийг одоогоор гүн уншаагүй.

Манай бодит таван FAQ probe-д proposed target-ийг эхэнд олсон нь BM25=10/15,E5=14/15. Эхгүй control дээр E5 өндөр similarity буцаасан тул энэ score-ийг probability/эхийн дэмжлэг гэж үзэхгүй. Энэ нь гүн уншлагаас гаргасан architecture шийдвэр: ranking, answerability, source validity ба router өөр хэмжилт/алхамтай байх ёстой. User/gold labels батлагдаагүй, таван FAQ жижиг тул ерөнхий дүгнэлт хийхгүй.

Full-paper уншлага ба хэрэглэгчийн уншсан явц дууссан гэж тэмдэглээгүй. [Бодит гаралт/протокол](../docs/experiments/retrieval-20261010.json).
