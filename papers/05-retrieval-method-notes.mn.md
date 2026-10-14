# BM25, E5 ба локал туршилтын холбоо — 2026.10.10

[Robertson/Zaragoza2009 зохиогчийн PDF](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) §3.4-ийн saturation ба уртаар хэвийнжүүлэх хэсгийг нягталсан. Термин дахин давтагдах нь оноог хязгааргүй шугаман өсгөхгүй; баримтын урт мөн нөлөөлнө. Манай baseline k1=1.5,b=0.75 ба эерэг log1p IDF ашигладаг; өгүүллийн бүх PRF/BM25F жорыг давтаагүй. Монгол залгавар/alias/stemming хэрэгжээгүй тул lexical coverage хязгаартай.

[Multilingual E5](https://arxiv.org/html/2402.05672v1) §2,§3,Хүснэгт 4/6,AppendixA ба [pinned small card](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3) usage-ийг нягталсан. Эх судалгаа contrastive pretraining ба labeled fine-tuning хийсэн. Бид тэдний бэлэн small жинг inference-д хэрэглэсэн. Query/passages prefix, mask-aware pooling, L2 normalization-ийг card-ийн дагуу ашигласан. MIRACL eval хэлний хүснэгтэд Монгол байхгүй; олон хэлтэй нэрээс Монгол чанарыг шууд дүгнэхгүй.

[BEIR](https://arxiv.org/abs/2104.08663)-ийн abstract нь BM25-ийг бат бөх baseline, зарим хүчтэй аргыг өндөр compute өртөгтэй гэж тайлагнадаг. Манай шийдвэр бол lexical ба dense аргыг ижил corpus/query/qrel дээр бодитоор шалгах. BEIR бүх хүснэгт/split-ийг одоогоор гүн уншаагүй.

Манай бодит таван FAQ probe-д proposed target-ийг эхэнд олсон нь BM25=10/15,E5=14/15. Эхгүй control дээр E5 өндөр similarity буцаасан тул энэ score-ийг probability/эхийн дэмжлэг гэж үзэхгүй. Энэ нь гүн уншлагаас гаргасан architecture шийдвэр: ranking, answerability, source validity ба router өөр хэмжилт/алхамтай байх ёстой. User/gold labels батлагдаагүй, таван FAQ жижиг тул ерөнхий дүгнэлт хийхгүй.

Full-paper уншлага ба хэрэглэгчийн уншсан явц дууссан гэж тэмдэглээгүй. [Бодит гаралт/протокол](../docs/experiments/retrieval-20261010.json).

## 2026.10.13–14: бүтэн эхийн сан дахь paired ablation

Энэ шинэ шатанд BM25-д Монгол үгийн alias/ил тод залгаврын хувилбар байгаа.
10.10-ны дээрх «stemming хэрэгжээгүй» нь тэр үеийн түүхэн baseline; одоогийн
код морфологийн сурсан модель ашигладаг гэсэн үг биш.

[RRF-ийн эх өгүүлэл](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf)-ийн хоёр
хуудсыг нягталсан. RRF нь `sum(1/(k+rank))`-аар эрэмбийг нэгтгэдэг; анхны
туршилт k=60 хэрэглэсэн. Манай өмнөх код k=30 хэвээр тул эх өгүүллийн бүх
туршилтыг давтсан гэж нэрлэхгүй. Энэ арга нь rank-ийг нэгтгэдэг учраас BM25
ба cosine оноог ижил probability болгох шаардлагагүй.

[Pinned E5 usage](https://huggingface.co/intfloat/multilingual-e5-small/raw/614241f622f53c4eeff9890bdc4f31cfecc418b3/README.md)-д
non-English хайлт ч query/passage prefix шаарддаг; манай код `query: ` болон
`passage: `, masked mean pooling, L2 normalization, max512 хэрэглэж байгааг
шалгасан. Эдгээрийг зөв хэрэглэсэн нь Монгол хэлний чанарыг батлахгүй.

Нэг 160 хэсгийн индекс, 30 target+3 no-candidate+3 router-control асуулт.
| Арга | Support@1 | Support@3 | Support@5 | MRR@5 |
|---|---:|---:|---:|---:|
| BM25 | 20/30 | 27/30 | 27/30 | 0.7722 |
| E5 | 7/30 | 16/30 | 23/30 | 0.4272 |
| RRF | 20/30 | 28/30 | 28/30 | 0.7667 |
| RRF + anchor/category дүрэм | 22/30 | 29/30 | 30/30 | 0.8400 |
| Одоогийн хайлт, нэмэлт topic/lexical guard-тай | 22/30 | 29/30 | 30/30 | 0.8400 |

Өмнөх 5 FAQ/15 асуултын BM25=10/E5=14 top1 дүнтэй шууд зөрчил гэж үзэхгүй:
асуулт, corpus, expected-label хүрээ өөр. Энэ шинэ багцад BM25 хүчтэй baseline;
дан E5 тааруу, RRF ба дүрмийн ахиц асуулт бүрт жигд биш. Нэмэлт дүрэмтэй top1
22 нь дан RRF 20-оос их боловч эдгээр асуултаар дүрэм тохируулсан тул шинэ
асуултад мөн сайжирна гэсэн баталгаа байхгүй. Pinned жинг inference-д ашигласан,
өөрсдөө сургаагүй. [Протокол/хязгаар](../CORE/ROADMAP-PROGRESS.mn.md).
