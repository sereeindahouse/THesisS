# BM25 ба E5 хайлтын бодит туршилт — 2026.10.10

Таван сургуулийн draft FAQ, ассистентийн зохиосон 15 өөр хэллэгтэй асуулт, тухайн corpus-д бүрэн хариултгүй таван асуултаар локал CPU туршилт хийсэн. Хүний баталсан gold эсвэл final test биш. Хувийн WAV/transcript ашиглаагүй.

| Арга | Зорьсон FAQ-г эхэнд олсон | Эхний гуравт олсон | MRR |
|---|---:|---:|---:|
| BM25 | 10/15 | 13/15 | 0.786 |
| E5 small | 14/15 | 15/15 | 0.967 |

E5 нь бэлэн хариулт үүсгэхгүй; FAQ-г эрэмбэлсэн. «Систем 93.3% зөв хариулдаг» гэсэн дүгнэлт биш. Тавхан candidate учраас top5 чанарын нотолгоо болохгүй. CS program/department-ийн ойролцоо агуулгад proposed label-ийг хүн дахин нягтлах шаардлагатай.

Хариултгүй таван асуултын хамгийн ойр FAQ-ийн E5 оноо 0.789–0.832. Өндөр similarity нь асуултад хариулах эх байна гэсэн баталгаа биш. Босго, татгалзалт/router, LLM генераци энд хэрэгжээгүй.

BM25 нь NFC/casefold, Unicode үгийн token, k1=1.5, b=0.75, эерэг log1p IDF ашигладаг; Монгол залгавар/alias боловсруулахгүй. E5 нь query:/passage: prefix, attention mask бүхий mean pooling, L2 normalization, 384 хэмжээтэй vector ашигласан. 512 token хязгаар; энэ багцад текст таслагдаагүй. Training/fine-tuning хийгээгүй.

[Анхны хоёр аргын түүхий ranking ба протокол](../../docs/experiments/retrieval-20261010.json), [тогтмол нийлбэрийн дараалалтай BM25](../../docs/experiments/bm25-deterministic-20261010.json). Файлууд нь нийтэд нээлттэй draft FAQ болон ассистентийн жишээ; хэрэглэгчийн хувийн яриа биш. Эдгээр нь тухайн үеийн кодын snapshot; дараагийн portability засварыг хийсний дараа unchanged E5 inference давтаагүй.

[BM25 зохиогчийн эх](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) · [E5 тайлан](https://arxiv.org/html/2402.05672v1) · [Аргын тэмдэглэл](../../papers/05-retrieval-method-notes.mn.md)
