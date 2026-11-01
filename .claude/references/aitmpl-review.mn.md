# aitmpl.com-оос THesisS-д юу хэрэгтэй вэ?

**Шалгасан: 2026.11.01.** Сайт, machine-readable тайлбар, GitHub-ийн дөрвөн skill ангиллыг үзэж, доорх найман `SKILL.md`-ийн үндсэн бичвэрийг уншсан. Сайтын бүх компонент, helper script, dependency-г аудитлаагүй. Судалгааны 45 өгүүллийг энэ ажлаар дахин бүтнээр уншсан гэсэн үг биш.

Каталогийн эх: [aitmpl.com](https://aitmpl.com/), [машин унших тайлбар](https://aitmpl.com/llms.txt), [GitHub](https://github.com/davila7/claude-code-templates). Энэ удаа харсан GitHub head `d04b6a997e4e96bfe51fedb739b73344815b5927`. Доорх нь тэр үеийн агуулгын үнэлгээ; шинэ хувилбар өөрчлөгдөж болно.

Skill нь загварын жинг сургадаг зүйл биш. Давтагддаг ажлыг яаж хийхийг заасан файл юм. Манай STT/RAG/TTS-ийн чанарыг өөрөө нэмэхгүй; шалтгаанаа зөв оношлох, ижил нөхцөлд харьцуулах, хийсэн ажлаа үнэн тайлагнахад тусална.

| Уншсан skill | Манай ажилд ашиглах зүйл | Шууд хуулж суулгаагүй шалтгаан |
|---|---|---|
| [systematic-debugging](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/development/systematic-debugging) | Шалтгаан → нэг таамаг → жижиг засвар → шалгалт | Өөр skill-ийн заавал хамаарал, манайд хамаарахгүй нөлөөллийн хувь, environment хэвлэх жишээг авахгүй. `/thesis-debug`-т товчилсон. |
| [verification-before-completion](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/development/verification-before-completion) | “Болсон” гэхийн өмнө яг нотолгоогоо харах | Бүх мэдэгдэлд бүтэн суитийг дахин ажиллуулах байдлаар хэрэглэхгүй. Тухайн өөрчлөлтөд тохирсон шинэ шалгалт хийнэ. `/thesis-debug`-т орсон. |
| [webapp-testing](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/development/webapp-testing) | Вэбийн ажиллагаа, DOM, зураг, browser log шалгах | Playwright/браузер, серверийн lifecycle шаарддаг. Одоогийн owner хамгаалалтыг тойрохгүй. Энэ setup-д helper/browser dependency суулгаж ажиллуулаагүй; шаардлагатай E2E ажилд дараа сонгоно. |
| [literature-review](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/scientific/literature-review) | Асуулт, хайлтын бүртгэл, давхардал, арга/өгөгдөл/хязгаар, эшлэл | AI зураг заавал үүсгэх, бусад scientific skill, PDF toolchain/эмнэлгийн сангийн хамаарал нь энд шаардлагагүй. `/thesis-research`-т хэрэгтэй зарчмыг тусгасан. |
| [scientific-critical-thinking](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/scientific/scientific-critical-thinking) | Нэг хүний dev-ийг нийт Монгол хэлний чанар болгож дүгнэхгүй; bias, хэмжүүр, sample-ийн хязгаар | Эмнэлгийн GRADE/ROB болон зураг үүсгэх ерөнхий чиглэлийг сургуулийн дипломд заавал мөрдүүлэхгүй. `/thesis-research`-т нийцүүлсэн. |
| [scientific-writing](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/scientific/scientific-writing) | Эхлээд бүтэц, дараа нь уншигдах өгүүлбэр; арга/дүн/тайлбарыг ялгах | IMRAD, жагсаалт хориглох, AI зураг заавал үүсгэх нь сургуулийн загвар, төлөвлөгөөний хүснэгтийг орлохгүй. Хүний үгээр тайлагнах зарчмыг `/thesis-weekly`-д хэрэглэсэн. |
| [llm-evaluation](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/ai-research/llm-evaluation) | Retrieval ба хариултын чанар, хүний үнэлгээг салгах ойлголт | Жишээ кодыг production гэж үзэхгүй: тайлбарлаагүй `llm_eval` interface, English-only BERTScore жишээ, хуучин API дуудлага, paired байдлыг харгалзаагүй t-test бий. Kappa-ийн boolean-key dictionary нь бүх ангиллыг зөв ялгахгүй. Манай протокол, байгаа scorer-ийг эхлээд хэрэглэнэ. |
| [rag-engineer](https://github.com/davila7/claude-code-templates/tree/main/cli-tool/components/skills/ai-research/rag-engineer) | Chunk, metadata, hybrid хайлт ба тусдаа retrieval үнэлгээг бодох | Ерөнхий зөвлөгөө. Манай SQLite/BM25/E5/RRF, эхийн ID сонголтыг Chroma/LangChain/GraphRAG болгон солих нотолгоо биш. Хэмжилтгүй архитектурын өөрчлөлт хийхгүй. |

## Бэлдсэн дөрвөн skill

Эдгээр нь гаднын багцыг бүхлээр суулгасан хуулбар биш; THesisS-ийн одоогийн дүрэм, сургуулийн зааварт тохируулан шинээр бичсэн заавар:

- `/thesis-resume` — шинэ чат/хязгаарын дараа бодит төлөвөө уншаад үргэлжлүүлэх.
- `/thesis-debug` — STT, хайлт, сонголт, TTS-ийн алдааг ялгаж засах, шалгах.
- `/thesis-research` — шийдвэртэй холбоотой primary уншлага, хязгаар ба харьцуулалт.
- `/thesis-weekly` — хийсэн ажлаас дэвтэр, багшийн асуулт, 5 минутын яриа гаргах.

Hook, MCP server, agent swarm, автомат paid API, telemetry/analytics сервер, model training суулгаагүй. Төсөлд одоогоор эдгээрийг нэмэх шаардлагыг нотлоогүй. Skill-үүд metadata-аараа олдож, үндсэн заавар нь хэрэгтэй үед ачаалагдана; бүх урт тайланг чат бүрд хуулж оруулах шаардлагагүй.

## Албан Claude заавар

- [Desktop Code ба CLI, нэг хөдөлгүүр ба shared configuration](https://code.claude.com/docs/en/desktop)
- [CLAUDE.md, memory, богино заавар](https://code.claude.com/docs/en/memory)
- [Project skill-ийн байршил, автоматаар сонгох ба /command](https://code.claude.com/docs/en/skills)
- [Windows суулгах албан арга](https://code.claude.com/docs/en/setup)
- [Pro төлөвлөгөө, хамт тооцогдох usage, subscription login ба API key](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan)

Pro нь хязгааргүй ажиллах эрх биш. Терминал руу шилжсэнээр тусдаа нэмэлт квот нээгдэхгүй. Бодит дансны боломж, хувилбар, `/usage`-ийг хэрэглэгчийн нэвтэрсний дараа шалгана. Нэмэлт төлбөр/credit-ийг энэ setup идэвхжүүлэхгүй.
