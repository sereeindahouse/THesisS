// One printable sheet for the reception desk: write down the questions visitors ask (2026-12-02, two weeks).
// The final evaluation of the thesis (3.6) uses these real questions. No personal data is written.
//   node tools/thesis_docx/reception_log.js <out.docx>
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType, BorderStyle, AlignmentType,
  PageOrientation, ShadingType,
} = require('docx');

const FONT = 'Times New Roman';
const t = (text, opts = {}) => new TextRun({ text, font: FONT, size: opts.size || 22, bold: opts.bold, italics: opts.italics });
const p = (runs, opts = {}) => new Paragraph({ children: Array.isArray(runs) ? runs : [t(runs, opts)], spacing: { after: opts.after ?? 80 },
  alignment: opts.align || AlignmentType.LEFT });

const line = { style: BorderStyle.SINGLE, size: 4, color: '000000' };
const borders = { top: line, bottom: line, left: line, right: line };
const cols = [
  ['№', 600], ['Огноо', 1200], ['Цаг', 900], ['Хэн асуусан', 2100], ['Асуулт (хүний хэлсэн үгээр)', 6000], ['Хаашаа явуулсан, юу гэж хариулсан', 3600],
];
const cell = (text, width, header) => new TableCell({
  borders, width: { size: width, type: WidthType.DXA },
  shading: header ? { fill: 'EEEEEE', type: ShadingType.CLEAR, color: 'auto' } : undefined,
  margins: { top: 60, bottom: 60, left: 80, right: 80 },
  children: [new Paragraph({ children: [t(text, { bold: header, size: header ? 20 : 22 })] })],
});
const rows = [new TableRow({ tableHeader: true, children: cols.map(([name, w]) => cell(name, w, true)) })];
for (let k = 1; k <= 22; k++) {
  rows.push(new TableRow({ height: { value: 520, rule: 'atLeast' }, children: cols.map(([, w], i) => cell(i === 0 ? String(k) : '', w, false)) }));
}
rows.splice(1, 0, new TableRow({ children: [
  cell('жишээ', 600, false), cell('12/02', 1200, false), cell('10:15', 900, false), cell('эцэг эх', 2100, false),
  cell('Хүүгийн ангийн багш хэдэн тоотод суудаг вэ?', 6000, false), cell('408 тоотыг хэлсэн', 3600, false)] }));

const doc = new Document({
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838, orientation: PageOrientation.LANDSCAPE },
      margin: { top: 720, bottom: 720, left: 720, right: 720 } } },
    children: [
      p([t('Ресепшнд асуусан асуултын бүртгэл', { bold: true, size: 30 })], { after: 60 }),
      p('Хугацаа: 2026 оны 12-р сарын 2-оос хоёр долоо хоног. Ирсэн хүн юу асуусныг хэлсэн үгээр нь товч бичнэ үү. '
        + 'Нэр, утас, регистр зэрэг хувийн мэдээлэл бичихгүй. «Хэн асуусан» хэсэгт зөвхөн оюутан, эцэг эх, элсэгч, зочин, ажил хайгч, бусад гэж бичнэ.'),
      p('Энэ асуултуудаар «ШМТК-ийн ухаалаг туслах» дипломын ажлын системийг үнэлнэ (систем зөв хариулж чадаж буйг шалгана). '
        + 'Асуултыг систем рүү оруулахаас өмнө ажилтны хариултыг үндэслэн зөв хариултыг тэмдэглэнэ.', { after: 160 }),
      new Table({ width: { size: cols.reduce((a, [, w]) => a + w, 0), type: WidthType.DXA }, columnWidths: cols.map(([, w]) => w), rows }),
      p([t('Бөглөсөн хуудсыг Б.Сэргэлэнд өгнө үү. Баярлалаа.', { italics: true, size: 20 })], { after: 0 }),
    ],
  }],
});
Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2], buf); console.log('wrote', process.argv[2]); });
