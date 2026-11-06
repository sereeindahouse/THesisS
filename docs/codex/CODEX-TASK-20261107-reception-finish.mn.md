# Codex-д өгөх даалгавар №2 — ресепшний замыг эцэслэх (2026.11.07)

**Өмнөх ажил:** `tools/import_school_tables.py`-ийг main-д нийлүүлсэн (`a7dfe12`). Импорт бэлэн боловч гурван зүйл дутуу:
1. «Одоо», «өнөөдөр» гэсэн асуултад цаг өгөхгүй (`reception_clock=None`).
2. Хянасан CSV-г системд суулгах команд байхгүй.
3. Чатаар бүтэн замыг шалгасан тест алга.

**⚠ Заавал:** өмнөх удаад `CORE/PROJECT-NOTE.mn.md`, `config/project-progress.json`, `CORE/THesisS.code-workspace` дахь Монгол текст «????» болж эвдэрсэн. Бүх файлыг **UTF-8**-аар уншиж, бичнэ (PowerShell-ийн `>` ба `Set-Content`-ийг ашиглахгүй, Python-ий `encoding='utf-8'`-ийг ашиглана). Commit хийхээс өмнө `git diff | grep -c '????'` нь 0 байх ёстой. Эдгээр 3 тэмдэглэлийн файлыг **огт өөрчлөхгүй** — тайлангаа зөвхөн `docs/codex/`-д бичнэ.

**Хийх:**
1. `rag_runtime.py`-д `reception_clock`-ийг Улаанбаатарын цагаар (UTC+8) өгнө. Тестэд цагийг тогтмол болгож болдог байна.
2. Суулгах командыг `tools/install_reception_tables.py` болгон бичнэ. Энэ нь `runtime/school-tables/<огноо>/`-ийн CSV ба metadata-г `data/reception/<хувилбар>/` руу хуулна. Нөхцөлүүд:
   - `--reviewed-by <нэр>` заавал байна.
   - `is_fake=true` бол татгалзана.
   - `config/reception-tables.json`-ийн `source`-ийг шинэчилнэ. Харин `enabled`-ийг **асаахгүй**.
   - `data/reception/` нь git-д орохгүй.
3. Бүтэн замын тест бичнэ: хуурамч өгөгдлийг импортлох → суулгах → тестийн дотор л `enabled=true` болгох → `/api/route` (эсвэл `rag_runtime.ChatRAG`)-аар 12 асуулт (`build_school_data_list.QUESTIONS`) асуух. Хариу бүр зөв хүснэгтээс гарч, «одоо хичээлтэй юу» асуултын хариу «Хуваариар бол» гэж эхлэх ёстой. Сүлжээ ба LLM ашиглахгүй.
4. `docs/reception-tables.mn.md`-д 4 алхмын заавар нэмнэ: сургуулийн Excel → импорт → хүн хянах → суулгах → асаах.

**Хийхгүй:** бодит өгөгдлөөр ресепшнийг асаахгүй. `rule_selector.py`, эхийн хамгаалалт, RAG хайлт, STT/Gemini-г өөрчлөхгүй. Шинэ хамаарал нэмэхгүй. Main-д шууд commit хийхгүй.

**Хүлээлгэж өгөх:** `codex/reception-finish-20261107` салаа, `docs/codex/RECEPTION-FINISH-REVIEW-20261107.mn.md` тайлан (команд, дүн, үлдсэн асуудал).

**Тест:** `.venv/Scripts/python.exe -B -X utf8 -m unittest tests.test_reception_tables tests.test_import_school_tables tests.test_install_reception_tables`
