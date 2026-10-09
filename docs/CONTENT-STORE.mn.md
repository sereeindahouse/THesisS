# Эхтэй агуулгын SQLite суурь

`content_store.py` нь JSON схемээр шалгасан эх, fact, FAQ-г SQLite-д хадгална. `import_content.py` нь импорт, төлөв, жагсаалт, ID-аар preview хийх команд. Энэ нь автомат асуултын router биш.

```powershell
py -3.11 import_content.py import data/content-draft-v1.json --allow-draft
py -3.11 import_content.py status
py -3.11 import_content.py list --allow-draft --as-of 2026-10-10
py -3.11 import_content.py preview faq.contact --allow-draft --as-of 2026-10-10
py -3.11 import_content.py preview faq.contact --as-of 2026-10-10
```

Эхний команд draft багцыг локал DB-д импортолно. Ижил агуулга дахин импортлоход шинэ багц/мөр нэмэхгүй. Багцын түүх хадгалагдана. Эхийн document_id+version-ын агуулгыг өөрчлөхөд шинэ version шаардана; хуучин эшлэл хуучин хувилбараа заана.

Draft preview-д хариулт, scope, эхийн ID/хувилбар/locator/URL, баталгааны төлөв харагдана. Сүүлийн команд ердийн горимтой: одоогийн агуулга draft тул answer хоосон, шалтгаан харагдана. Импорт автоматаар баталгаа өгдөггүй.

FAQ → fact → source бүх хамаарлыг шалгана. Илэрхий rejected эсвэл огнооны хүрээнээс гарсан агуулгыг draft горимоор ч хэрэглэж болохгүй. Огноо тодорхойгүй мөрийг unknown_validity_records-д харуулна; үүнийг өнөөдрийн хүчинтэй мэдээлэл гэж батлахгүй. Хүний баталгаа болон хугацааны бодлогыг агуулгын ажлын явцад нөхнө.

Өөр DB сонгох бол global --db-г дэд командын өмнө өгнө:

```powershell
py -3.11 import_content.py --db runtime/example.db status
py -3.11 -m unittest discover -s tests -v
```

DB, импортын гаралт нь локал runtime өгөгдөл; Git-д орохгүй. Судалгааны test-д зохиомол fixture хэрэглэнэ; сургуулийн draft-г тестээр approved болгож өөрчилдөггүй.
