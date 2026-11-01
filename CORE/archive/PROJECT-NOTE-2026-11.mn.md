# PROJECT-NOTE-ийн 2026.11-ийн архив

Үндсэн тэмдэглэлээс 2026.11.01-нд үгчлэн зөөв. Хуучин төлөвийг өнөөдрийнх гэж бүү ойлго.

<!-- claude-handoff-20261101:start -->
## 2026.11.01 — Claude Code-д үргэлжлүүлэх заавар

**Хийсэн:** GitHub `main` ба локал HEAD-ийг `773d1c0331387fb92f3eabb89cc0afbac969b6c9` дээр тулгаж, хамгийн сүүлийн II checkpoint, model ID, сургуулийн хураангуй, Git-д байгаа/локалд үлдсэн эхүүдийг ялгав. `CLAUDE.md`, [үргэлжлүүлэх зураглал](CLAUDE-HANDOFF.mn.md), дөрвөн project skill, read-only `tools/claude_context.py`, `CORE/CLAUDE.cmd` бэлтгэв. aitmpl-ийн найман үндсэн skill entry-г уншиж, дипломын дүрэмд тохирох аргачлалыг тусгасан; бүх helper/dependency-г суулгасан гэсэн үг биш.

**Нотолгоо/зааг:** дөрвөн skill-ийн бүтэц тэнцсэн; read-only snapshot бодит төсөл, дутуу эх, эвдэрсэн config, хамааралгүй credential файлд хүрэхгүй нөхцөлөөр шалгагдсан. Note-ийн 6 ба sync-ийн 9 тест PASS; sync --check зөрүүгүй. Албан Claude Code stable 2.1.309 сууж, launcher --version тэнцсэн; өмнөх хэрэглэгчийн PATH-ийг хадгалж зөвхөн launcher-ийн зам нэмсэн. Auth status loggedIn=false; хэрэглэгч Pro дансаараа өөрөө нэвтэрнэ. Хуучин 185/202/24 тестийг энэ ажлаар дахин хийсэн гэж үзэхгүй. Шинэ Google/LLM/TTS inference, аудио дамжуулалт, сургалт, хүний үнэлгээ үүсгээгүй; II-ийн одоогийн focus ба production загвар/өгөгдөл хэвээр. Шинэ setup-ийн publication нь локал өөрчлөлт; энэ ажлаар commit/push хийгээгүй.

**Үлдсэн → дараагийн алхам:** хэрэглэгч өөрийн Pro дансаар Claude Code-д нэвтэрч энэ local хавтсыг сонгоод `/thesis-resume` ажиллуулна. Claude-д данс шилжсэнээр хувийн эх cloud/GitHub руу автоматаар очихгүй. Шинэ хүний асуулт, утга/сонсгол/засах хөдөлмөр, 11/2-ны STT шийдвэр нь өмнөх current блокийн дагуу бодит ажил хэвээр. Өмнө байсан гурван локал өөрчлөлтийг хадгалсан.
<!-- claude-handoff-20261101:end -->

<!-- memory-structure-20261101:start -->
## 2026.11.01 — Санах ойн бүтэц, архив, семинарын хуваарьт ажил

**Хийсэн:** Энэ тэмдэглэл 10.29-нөөс 3 хоногт 74KB/314 мөр болж өссөн тул 10.29–10.30-ны түүхэн блок ба огноотой бүртгэлийг [archive/PROJECT-NOTE-2026-10.mn.md](archive/PROJECT-NOTE-2026-10.mn.md)-д үгчлэн зөөв (устгаагүй). `CLAUDE.md`-д санах ой/context-ийн дүрэм ба Compact Instructions, `/thesis-resume`-д сар бүрийн архивын алхам, `CLAUDE-HANDOFF`-д архивын заалт нэмэв. `.gitignore`-д `CORE/archive/`-ийг нийтийн болгов. `.claude/settings.local.json`-оос 4 skill-ийн `name-only`-г хассан тул skill-үүд автоматаар сонгогдоно. claude.ai дээр «Thesis seminar prep» хуваарьт ажил: даваа бүр 19:42, нийтийн repo-оос уншиж дэвтрийн ноорог/5 минутын яриа гаргана.

**Нотолгоо:** Зөөлтийн өмнө ба дараа `sync_project_note.py --check` synced=true, `tests.test_project_note` 6/6 OK (VM-ийн Python 3.10). Анхны мөр бүр note эсвэл архивт байгааг script-ээр тулгасан (дутуу 0); note ба архивын харьцангуй холбоос эвдэрсэн 0.

**Хязгаар → дараагийн алхам:** Commit/push хийгээгүй. Windows `.venv`-ээр бүтэн суит ажиллуулаагүй. Хэрэглэгч VS Code-д шинэ сесс нээж `/thesis-resume`-ээр эхэлнэ.
<!-- memory-structure-20261101:end -->

<!-- plan-and-slides-20261101:start -->
## 2026.11.01 — Төлөвлөгөө 5-р сар хүртэл, ШМТК загварын семинарын PPT

**Хийсэн:** `WEEKLY-PLAN`-д «plan-update-20261101» блок (сар бүрийн ажил), RQ2-ийг "баримтаас шууд хариулдаг систем хэр зөв, бүрэн вэ", W02-д Gemma-г тохиргоогоор унтраах, W08-ийг "Дүрмээр эх сонгохыг сайжруулах", W17-д нэг удаагийн эргэх цэг. `config/project-progress.json`-ийн RQ2 шинэчлэгдсэн. Түр ноорог `archive/PLAN-DRAFT-2026-11-01.mn.md` болсон. Сургуулийн `lekts_4.pdf` загвараар `tools/nmct_slides/` (лого, тамга, барилгын зураг, cover/content/table/thanks) хийж, 11/03-ны 10 слайдын PPT ба яриаг `CORE/seminar-2026-11-03/` (хувийн) хадгалсан.

**Нотолгоо:** `tests.test_project_plan`, `test_project_note`, `test_sync_project_note` 47 OK, `test_project_plan_ui` OK; `public_plan` 32 долоо хоног уншсан; `sync_project_note.py --check` synced. PPT validate PASS, 10 слайд хараар шалгасан.

**Хязгаар → дараагийн алхам:** Gemma-г кодонд хараахан унтраагаагүй (VS Code, W02). Commit хийгээгүй. Сүүлийн слайдын шинэ хэлбэрийг багштай тулгана.
<!-- plan-and-slides-20261101:end -->
