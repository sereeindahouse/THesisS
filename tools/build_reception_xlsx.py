"""Ресепшний мэдээлэл цуглуулах Excel загвар (сургуульд өгөх)."""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.comments import Comment

NAVY, LIGHT, FILL, EX = "0E3199", "E8F4FB", "FFF2CC", "7F7F7F"
F = "Arial"
thin = Side(style="thin", color="A6A6A6")
BOX = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD_FONT = Font(name=F, bold=True, color="FFFFFF", size=11)
HEAD_FILL = PatternFill("solid", fgColor=NAVY)
IN_FILL = PatternFill("solid", fgColor=FILL)
EX_FONT = Font(name=F, italic=True, color=EX, size=10)
BODY = Font(name=F, size=10)
SITE_FONT = Font(name=F, size=10, color="000000")
WRAP = Alignment(wrap_text=True, vertical="top")
EMPTY_ROWS = 60

wb = Workbook()

# ---------- 0. Заавар ----------
ws = wb.active
ws.title = "Заавар"
ws.sheet_view.showGridLines = False
ws.column_dimensions["A"].width = 3
ws.column_dimensions["B"].width = 26
ws.column_dimensions["C"].width = 90
r = 2
ws.cell(r, 2, "Ресепшний туслах системд хэрэгтэй мэдээлэл").font = Font(name=F, bold=True, size=16, color=NAVY)
r += 1
ws.cell(r, 2, "Шинэ Монгол Технологийн Коллеж · Компьютерын ухааны тэнхимийн төгсөлтийн ажил").font = Font(name=F, size=10, color=EX)
r += 2
rows = [
    ("Юунд хэрэгтэй вэ?", "Сургуулийн 1-р давхрын ресепшнд ажиллах туслах систем хийж байна. Ирсэн хүн \"Соронзонболд багш хаана байна?\", \"Компьютерын ухааны 2-р курсын анги хаана вэ?\", \"Номын сан хэддүгээр давхарт вэ?\" гэж асуухад хариулах ёстой. Энэ мэдээлэл сургуулийн сайтад байхгүй тул танаас хүсэж байна."),
    ("Хэн бөглөх вэ?", "Сургалтын алба, тэнхим, захиргаа. Мэдэх хэсгээ л бөглөхөд болно; бүх хуудсыг заавал дуусгах шаардлагагүй."),
    ("Яаж бөглөх вэ?", "Шар нүднүүдэд бичнэ. Саарал налуу бичигтэй мөр нь ЖИШЭЭ — түүнийг устгах эсвэл дээр нь бичиж болно. Цэнхэр мөр нь сургуулийн сайтаас авсан мэдээлэл — зөв эсэхийг шалгаад өрөө, цагийг нь нөхнө үү."),
    ("Хуудсууд", "1_Өрөө · 2_Багш_ажилтан · 3_Анги · 4_Хичээлийн_хуваарь · 5_Үйлчилгээ. Сүүлийн \"Явц\" хуудас хэдэн мөр бөглөгдсөнийг автоматаар тоолно."),
    ("Нийтэд харуулах", "Мөр бүрд \"Тийм/Үгүй\" гэж сонгоно. \"Үгүй\" гэсэн мэдээллийг систем ресепшнд харуулахгүй."),
    ("Хувийн мэдээлэл", "Хувийн утас, гэрийн хаяг, оюутны нэрс, дүн зэрэг хувийн мэдээлэл бүү оруулна уу. Багш \"одоо\" хаана байгааг систем зөвхөн энэ хичээлийн хуваариар хэлнэ (\"Хуваариар бол одоо 405 тоотод хичээлтэй байх ёстой\"). Хүнийг хянахгүй."),
    ("Мэдлэгийн мод", "Энэ мэдээлэл системийн мэдлэгийн модонд шинээр нэмэгдэх 3 хүрээ болно: Байршил ба өрөө (1, 5), Багш ба ажилтан (2), Анги ба хичээлийн хуваарь (3, 4)."),
    ("Хугацаа", "Боломжтой бол 2026.12.20-ноос өмнө. 2-р улирлын хуваарь гарахад 4-р хуудсыг дахин шинэчилнэ."),
    ("Буцааж өгөх", "Бөглөсөн файлыг оюутан ________________ (утас/имэйл: ________________)-д өгнө үү."),
]
for k, v in rows:
    ws.cell(r, 2, k).font = Font(name=F, bold=True, size=11, color=NAVY); ws.cell(r, 2).alignment = WRAP
    c = ws.cell(r, 3, v); c.font = Font(name=F, size=11); c.alignment = WRAP
    ws.row_dimensions[r].height = 16 * (len(v) // 80 + 1) + 6
    r += 1
r += 1
ws.cell(r, 2, "Тэмдэглэгээ").font = Font(name=F, bold=True, size=11, color=NAVY)
for txt, fill, font in (("Бөглөх нүд", IN_FILL, BODY), ("Сайтаас авсан, шалгах", PatternFill("solid", fgColor=LIGHT), SITE_FONT), ("ЖИШЭЭ мөр", None, EX_FONT)):
    r += 1
    c = ws.cell(r, 3, txt); c.font = font; c.border = BOX
    ws.row_dimensions[r].height = 18
    if fill: c.fill = fill
r += 2
ws.cell(r, 2, "Эх сурвалж").font = Font(name=F, bold=True, size=10, color=EX)
ws.cell(r, 3, "Тэнхимийн нэр, эрхлэгчийн нэрс: nmct.edu.mn/departments (2026.11.01-нд уншсан).").font = Font(name=F, size=10, color=EX)

# ---------- helpers ----------
def sheet(title, cols, example, prefill=(), validations=(), note=None):
    s = wb.create_sheet(title)
    for i, (name, width, comment) in enumerate(cols, 1):
        c = s.cell(1, i, name); c.font = HEAD_FONT; c.fill = HEAD_FILL; c.border = BOX
        c.alignment = Alignment(wrap_text=True, vertical="center")
        if comment: c.comment = Comment(comment, "THesisS")
        s.column_dimensions[c.column_letter].width = width
    s.row_dimensions[1].height = 32
    s.freeze_panes = "A2"
    row = 2
    for i, v in enumerate(example, 1):
        c = s.cell(row, i, v); c.font = EX_FONT; c.border = BOX
    row += 1
    for rec in prefill:
        for i, v in enumerate(rec, 1):
            c = s.cell(row, i, v); c.border = BOX
            c.fill = PatternFill("solid", fgColor=LIGHT) if v not in (None, "") else IN_FILL
            c.font = SITE_FONT
        row += 1
    first_input = row
    for rr in range(row, row + EMPTY_ROWS):
        for i in range(1, len(cols) + 1):
            c = s.cell(rr, i); c.fill = IN_FILL; c.border = BOX; c.font = BODY
    last = row + EMPTY_ROWS - 1
    for col_letter, dv in validations:
        dv.add(f"{col_letter}2:{col_letter}{last}"); s.add_data_validation(dv)
    if note:
        c = s.cell(last + 2, 1, note); c.font = Font(name=F, italic=True, size=9, color=EX)
    return s, last

yesno = lambda: DataValidation(type="list", formula1='"Тийм,Үгүй"', allow_blank=True)
floor = lambda: DataValidation(type="whole", operator="between", formula1="-1", formula2="12", allow_blank=True,
                               error="Давхар -1-ээс 12 хүртэл бүхэл тоо", showErrorMessage=True)
day = lambda: DataValidation(type="list", formula1='"Даваа,Мягмар,Лхагва,Пүрэв,Баасан,Бямба,Ням"', allow_blank=True)
time_ = lambda: DataValidation(type="time", operator="between", formula1="0", formula2="0.999988", allow_blank=True,
                               error="Цагийг 08:00 хэлбэрээр бичнэ үү", showErrorMessage=True)

DEPTS = ["Ерөнхий эрдмийн тэнхим", "Компьютерын ухааны тэнхим", "Механик инженерийн тэнхим",
         "Барилгын дэд бүтцийн инженерийн тэнхим", "Цахилгаан электроникийн инженерийн тэнхим", "Химийн инженерийн тэнхим"]
dept = lambda: DataValidation(type="list", formula1='"' + ",".join(DEPTS) + ',Захиргаа,Бусад"', allow_blank=True)

# ---------- 1. Өрөө ----------
s1, l1 = sheet("1_Өрөө",
    [("Өрөөний дугаар", 16, "Хаалган дээрх дугаар, жишээ: 405"), ("Давхар", 9, "Тоогоор: 1, 2 ... Подвал бол -1"),
     ("Нэр / зориулалт", 32, "Анги, лаборатори, тэнхимийн өрөө, номын сан гэх мэт"), ("Тэнхим", 30, None),
     ("Хэрхэн очих", 36, "Жишээ: шатнаас гараад баруун тийш"), ("Нийтэд харуулах", 12, None)],
    ["405", 4, "Компьютерын лаборатори", "Компьютерын ухааны тэнхим", "Шатнаас гараад баруун тийш", "Тийм"],
    prefill=[["602", 6, "", "", "", ""]],
    validations=[("B", floor()), ("D", dept()), ("F", yesno())],
    note="3-р мөр: сайтын мэдээнд \"ШМТК-ийн 6 давхрын 602 тоот\" гэж бичигдсэн. Нэр/зориулалтыг нөхнө үү.")
s1["B2"].number_format = "0"

# ---------- 2. Багш, ажилтан ----------
heads = [["Б.Сэлмаа", DEPTS[0], "Тэнхимийн эрхлэгч"], ["Н.Соронзонболд", DEPTS[1], "Тэнхимийн эрхлэгч"],
         ["Б.Билгүүн", DEPTS[2], "Тэнхимийн эрхлэгч"], ["Б.Болорцэцэг", DEPTS[3], "Тэнхимийн эрхлэгч"],
         ["Д.Түвшин", DEPTS[4], "Тэнхимийн эрхлэгч"], ["Д.Алтанзул", DEPTS[5], "Тэнхимийн эрхлэгч"]]
s2, l2 = sheet("2_Багш_ажилтан",
    [("Овог нэр", 20, "Жишээ: Н.Соронзонболд"), ("Тэнхим / нэгж", 34, None), ("Албан тушаал", 20, None),
     ("Өрөөний дугаар", 14, "1_Өрөө хуудасны дугаартай ижил"), ("Уулзах өдөр, цаг", 26, "Жишээ: Мягмар, Пүрэв 14:00–16:00"),
     ("Нийтэд харуулах", 12, None)],
    ["Б.Жишээ", "Компьютерын ухааны тэнхим", "Багш", "405", "Мягмар 14:00–16:00", "Тийм"],
    prefill=[h + ["", "", ""] for h in heads],
    validations=[("B", dept()), ("F", yesno())],
    note="Цэнхэр мөрүүд: nmct.edu.mn/departments-ийн тэнхимийн эрхлэгчид. Өрөө, уулзах цагийг нөхнө үү. Хувийн утас бүү бичнэ үү.")

# ---------- 3. Анги ----------
s3, l3 = sheet("3_Анги",
    [("Бүлгийн нэр", 16, "Сургуулийн хэрэглэдэг нэр, жишээ: КУ-2"), ("Тэнхим", 34, None), ("Курс", 8, "1–5"),
     ("Үндсэн өрөө", 14, "Ихэвчлэн хичээллэдэг өрөө"), ("Ангийн багш", 20, None), ("Нийтэд харуулах", 12, None)],
    ["КУ-2 (жишээ)", "Компьютерын ухааны тэнхим", 2, "405", "Б.Жишээ", "Тийм"],
    validations=[("B", dept()), ("C", DataValidation(type="whole", operator="between", formula1="1", formula2="5", allow_blank=True)), ("F", yesno())])

# ---------- 4. Хуваарь ----------
s4, l4 = sheet("4_Хичээлийн_хуваарь",
    [("Улирал", 14, "Жишээ: 2026–2027 I"), ("Бүлэг", 14, "3_Анги хуудасны нэртэй ижил"), ("Гараг", 11, None),
     ("Эхлэх", 9, "08:00 хэлбэрээр"), ("Дуусах", 9, None), ("Хичээл", 28, None), ("Багш", 20, None), ("Өрөө", 10, None)],
    ["2026–2027 I", "КУ-2 (жишээ)", "Мягмар", "10:00", "11:30", "Өгөгдлийн бүтэц", "Б.Жишээ", "405"],
    validations=[("C", day()), ("D", time_()), ("E", time_())],
    note="Систем \"одоо хаана байна?\" гэвэл энэ хуудсыг одоогийн гараг, цагтай тулгана. Хуваарь өөрчлөгдвөл шинэ хувилбараа өгнө үү.")
for rr in range(2, l4 + 1):
    s4[f"D{rr}"].number_format = "hh:mm"; s4[f"E{rr}"].number_format = "hh:mm"

# ---------- 5. Үйлчилгээ ----------
services = ["Ресепшн", "Сургалтын алба", "Номын сан", "Цайны газар", "Эмнэлгийн өрөө", "Ариун цэврийн өрөө", "Биеийн тамирын заал", "Санхүү, нягтлан"]
s5, l5 = sheet("5_Үйлчилгээ",
    [("Үйлчилгээ", 24, None), ("Давхар", 9, None), ("Өрөөний дугаар", 14, None), ("Ажлын цаг", 26, "Жишээ: Даваа–Баасан 09:00–18:00"),
     ("Тайлбар", 34, None), ("Нийтэд харуулах", 12, None)],
    ["Номын сан (жишээ)", 3, "301", "Даваа–Баасан 09:00–17:00", "", "Тийм"],
    prefill=[[x, "", "", "", "", ""] for x in services],
    validations=[("B", floor()), ("F", yesno())])

# ---------- 6. Явц (formulas) ----------
sp = wb.create_sheet("Явц")
sp.sheet_view.showGridLines = False
sp.column_dimensions["A"].width = 26; sp.column_dimensions["B"].width = 18; sp.column_dimensions["C"].width = 50
for i, h in enumerate(["Хуудас", "Бөглөсөн мөр", "Юуг тоолдог"], 1):
    c = sp.cell(1, i, h); c.font = HEAD_FONT; c.fill = HEAD_FILL; c.border = BOX
# Count from row 3 (row 2 is the example). Key column must be filled.
checks = [("1_Өрөө", l1, "C", "Нэр/зориулалт бөглөгдсөн өрөө"),
          ("2_Багш_ажилтан", l2, "D", "Өрөөний дугаар бөглөгдсөн хүн"),
          ("3_Анги", l3, "A", "Нэр бичигдсэн бүлэг"),
          ("4_Хичээлийн_хуваарь", l4, "C", "Гараг бөглөгдсөн хичээл"),
          ("5_Үйлчилгээ", l5, "C", "Өрөө бөглөгдсөн үйлчилгээ")]
for i, (name, last, col, what) in enumerate(checks, 2):
    sp.cell(i, 1, name).font = BODY
    c = sp.cell(i, 2, f"=COUNTA('{name}'!{col}3:{col}{last})"); c.font = BODY; c.border = BOX
    sp.cell(i, 3, what).font = Font(name=F, size=10, color=EX)
sp.cell(len(checks) + 2, 1, "Нийт").font = Font(name=F, bold=True)
sp.cell(len(checks) + 2, 2, f"=SUM(B2:B{len(checks)+1})").font = Font(name=F, bold=True)
sp.cell(len(checks) + 4, 1, "Жишээ мөрийг (2-р мөр) тоолохгүй.").font = Font(name=F, italic=True, size=9, color=EX)

for w in wb.worksheets:
    w.page_setup.orientation = "landscape"
    w.page_setup.paperSize = w.PAPERSIZE_A4
    w.page_setup.fitToWidth = 1
    w.page_setup.fitToHeight = 0
    w.sheet_properties.pageSetUpPr.fitToPage = True
    w.print_title_rows = "1:1" if w.title not in ("Заавар", "Явц") else None
out = "Ресепшний_мэдээлэл_цуглуулах_загвар.xlsx"
wb.save(out)
print(out)
