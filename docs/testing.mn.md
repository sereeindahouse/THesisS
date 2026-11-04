# Бүх тестийг нэг командаар ажиллуулах

Төслийн үндсэн хавтсаас, шаардлагатай сангууд суусан Python 3.11 орчинд:

```powershell
python -m unittest discover
```

`tests/__init__.py` нь `tests`-ийг багц болгож, өмнөх тестүүдийн хооронд
хуваалцдаг `from test_… import …` fixture импортуудыг хэвээр ажиллуулна.
Тест сонгож хасах, хүлээгдэж буй дүнг өөрчлөх, алдааг нуух өөрчлөлт ороогүй.
Тодорхой модулийг шалгах бол `python -m unittest tests.test_reception_tables`
гэж ажиллуулж болно.

## Бодит өгөгдөлд хүрэхгүй шалгах

Зарим хуучин интеграцийн тест localhost HTTP сервер нээж, зохиомол SQLite,
WAV, credential fixture-ийг түр хавтсанд үүсгэдэг. `test_public_launcher`
ердийн ажиллуулалтаар төслийн `runtime/` дотор зохиомол supervisor файл
үүсгэдэг тул хувийн runtime-д огт хүрч болохгүй ажлын үед үндсэн суитыг
шууд ажиллуулахгүй.

Дараах туслах нь зөвхөн код, нийтийн тохиргоо, долоо хоногийн төлөвлөгөө,
FAKE fixture-ийг шинэ системийн түр хавтсанд хуулж, бүх тестийн discovery-г
өөрчлөлтгүй ажиллуулна. Эх төслийн runtime, модель, аудио, DB, нууц,
бодит transcript-ийг уншихгүй, хуулбарлахгүй. Нийтийн сургуулийн өгөгдөл
хэрэглэдэг өмнөх тестэд зориулж `data/`-аас зөвхөн дараах дөрвөн JSON-ийг
яг нэрээр нь зөвшөөрсөн:

- `data/content-draft-v1.json`
- `data/content-draft-v2-20261015.json`
- `data/content-evidence-v2-20261015.json`
- `data/rag-locked-questions-20261102.json`

Эдгээр нь нийтийн сургуулийн баримт/асуултын багц; бодит ярианы transcript
эсвэл хувийн DB биш. `data/`-ийн бусад файл, papers/reports доторх түүхий
үр дүн, аудио, модель хуулбарлахгүй.

```powershell
python tools/run_offline_unit_tests.py --list-only
```

Энэ нь бүх тестийг олж импортлоод тоог хэвлэнэ; тестийн үйлдлүүдийг
гүйцэтгэхгүй. Бүх сүлжээний холболтыг хориглосон ажиллуулалт:

```powershell
python tools/run_offline_unit_tests.py
```

Бүр түр хавтас дахь зохиомол runtime/model/audio/DB fixture үүсгэх,
уншихыг хориглох нэмэлт хатуу горим:

```powershell
python tools/run_offline_unit_tests.py --strict-assets
```

Socket хориглосон горимд HTTP/loopback интеграцийн тестүүд, `--strict-assets`
горимд нэмээд эдгээр түр fixture шаарддаг тестүүд алдаа өгч болно.
Тэдгээрийг тэнцсэн эсвэл алгассан гэж тооцохгүй. Зөвхөн зохиомол локал
серверүүдийн loopback холболтыг зөвшөөрсөн үед бүтэн суитыг:

```powershell
python tools/run_offline_unit_tests.py --allow-loopback
```

Энэ горимд ч гадаад хаягийн холболтыг Python audit guard хориглоно.
Одоогийн ажилд localhost API хүртэл хориглосон бол энэ сүүлийн командыг
зөвшөөрөлгүй ажиллуулахгүй. Дүн тайлагнахдаа ашигласан command,
Python/орчин, нийт ажилласан тест, PASS, FAIL, ERROR, SKIP-ийг ялгана.
Discovery-ийн тоо нь тест тэнцсэн тоо биш.

Дүнг шинэ JSON файлд хадгалах жишээ:

```powershell
python tools/run_offline_unit_tests.py --strict-assets --report docs/test-run-new.json
```

Тайланд ажилласан тест, PASS, FAIL, ERROR, SKIP, expected failure,
unexpected success, алдаатай тестийн ID ба SKIP-ийн шалтгаан орно.
FAIL/ERROR-ийн тоонд subtest-үүд орж болох тул тэдгээрийг нийт ажилласан
тесттэй механикаар нэмж тааруулахгүй. Тайлангийн нэр `.json` байх ёстой;
runtime/models/audio/secrets/.git дотор бичихгүй, байгаа файлыг дарахгүй.
Ижил тайланг дахин ашиглах бол шинэ нэр сонгоно. `--list-only` нь тестийн
үйлдэл ажиллуулахгүй тул гүйцэтгэлийн PASS/FAIL тайлан үүсгэхгүй.

Node.js шаарддаг UI handler тестүүд Node байхгүй бол өөрсдийн одоо байгаа
дүрмээр SKIP; TLS fixture-д OpenSSL, Windows-ийн тусгай тестэд Windows
шаардлагатай. Тэдгээрийн шалтгааныг unittest-ийн гаралттай нь тайлагнана.
Gemini Live transport-ийн mock-ийг импортлоход `websockets==15.0.1`
шаардлагатай (`requirements.txt`); энэ нь жинхэнэ Gemini дуудах зөвшөөрөл
биш. Бичгэн үндсэн тестийн ихэнх нь Python standard library ашиглана;
тодорхой dependency дутвал тухайн ERROR-ийг нуухгүй. Шинэ dependency
эсвэл модель татах нь энэ шалгалтын хэсэг биш.
