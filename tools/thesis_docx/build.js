// Build the supervisor-draft Word file from the flattened thesis markdown.
// node build.js <teacher.md> <main_teacher.aux> <main_teacher.bbl> <figdir> <logo.png> <acrolist.tex> <out.docx>
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
  WidthType, BorderStyle, ImageRun, PageBreak, TableOfContents, LevelFormat, Footer, PageNumber,
  ShadingType, TabStopType,
} = require('docx');

const [mdPath, auxPath, bblPath, figDir, logoPath, acroPath, outPath] = process.argv.slice(2);
const md = fs.readFileSync(mdPath, 'utf8').replace(/\\fullinput\{[^}]*\}/g, '').replace(/\\quad\s*/g, '    ').split(/\r?\n/);
const aux = fs.readFileSync(auxPath, 'utf8');
const cite = {};
for (const m of aux.matchAll(/\\bibcite\{([^}]+)\}\{\{(\d+)\}/g)) cite[m[1]] = Number(m[2]);

const FONT = 'Times New Roman';
const SIZE = 24; // 12 pt
const LINE = 360; // 1.5 lines
const TEXT_W = 9638; // A4 21cm - 2x2cm? use 3cm left, 1.5cm right => 16.5cm = 9355; keep 17cm
const FIGS = { '1.1': 'usecase_diagram', '3.1': 'data_model', '3.2': 'knowledge_tree', '3.3': 'system_structure',
  '3.4': 'activity_diagram', '3.5': 'sequence_diagram' };

function latexToText(s) {
  return s.replace(/\\geq\s*/g, '≥ ').replace(/\\leq\s*/g, '≤ ').replace(/\\times/g, '×')
    .replace(/\\mathrm\{([^}]*)\}/g, '$1').replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, '($1) / $2')
    .replace(/\\%/g, '%').replace(/~/g, ' ').replace(/\s+/g, ' ').trim();
}

// inline: **bold**, *italic*, $math$, [citekeys]
function runs(text, base = {}) {
  text = text.replace(/\[([a-z][a-z0-9_]*(?:,\s*[a-z][a-z0-9_]*)*)\]/g, (all, keys) => {
    const nums = keys.split(/,\s*/).map(k => cite[k]);
    if (nums.some(n => !n)) return all;
    return '[' + nums.join(', ') + ']';
  });
  const out = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\$[^$]+\$)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), font: FONT, size: base.size || SIZE, bold: base.bold, italics: base.italics }));
    const tok = m[0];
    if (tok.startsWith('**')) out.push(new TextRun({ text: tok.slice(2, -2), bold: true, italics: base.italics, font: FONT, size: base.size || SIZE }));
    else if (tok.startsWith('$')) out.push(new TextRun({ text: latexToText(tok.slice(1, -1)), italics: /^[A-Za-z]$/.test(tok.slice(1, -1)), bold: base.bold, font: FONT, size: base.size || SIZE }));
    else out.push(new TextRun({ text: tok.slice(1, -1), italics: true, bold: base.bold, font: FONT, size: base.size || SIZE }));
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), font: FONT, size: base.size || SIZE, bold: base.bold, italics: base.italics }));
  return out;
}

const body = (text) => new Paragraph({ children: runs(text), alignment: AlignmentType.JUSTIFIED,
  spacing: { line: LINE, after: 120 }, indent: { firstLine: 567 } });
const center = (text, opts = {}) => new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: opts.after ?? 0, before: opts.before ?? 0 },
  children: [new TextRun({ text, font: FONT, size: opts.size || SIZE, bold: opts.bold })] });

function pngSize(file) {
  const b = fs.readFileSync(file);
  return { w: b.readUInt32BE(16), h: b.readUInt32BE(20), data: b };
}
function image(file, maxWpx = 600, maxHpx = 820) {
  const { w, h, data } = pngSize(file);
  const s = Math.min(maxWpx / w, maxHpx / h, 1);
  return new Paragraph({ alignment: AlignmentType.CENTER, keepNext: true, spacing: { before: 120, after: 60 },
    children: [new ImageRun({ type: 'png', data, transformation: { width: Math.round(w * s), height: Math.round(h * s) } })] });
}

const border = { style: BorderStyle.SINGLE, size: 4, color: '000000' };
const borders = { top: border, bottom: border, left: border, right: border };
function table(rows) {
  const ncol = Math.max(...rows.map(r => r.length));
  const total = 9000;
  // width by average text length per column, with a floor
  const lens = Array.from({ length: ncol }, (_, i) => Math.max(4, ...rows.map(r => (r[i] || '').length)));
  const sum = lens.reduce((a, b) => a + Math.min(b, 60), 0);
  const longest = Array.from({ length: ncol }, (_, i) => Math.max(3, ...rows.map(r => Math.max(0, ...((r[i] || '').replace(/\*/g,'').split(/\s+/).map(w => w.length))))));
  let widths = lens.map((l, k) => Math.max(longest[k] * 125 + 200, Math.round(total * Math.min(l, 60) / sum)));
  const over = widths.reduce((a, b) => a + b, 0) / total; if (over > 1) widths = widths.map(w => Math.round(w / over));
  const fix = total - widths.reduce((a, b) => a + b, 0); widths[widths.length - 1] += fix;
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: widths, alignment: AlignmentType.CENTER,
    rows: rows.map((r, ri) => new TableRow({
      tableHeader: ri === 0,
      children: Array.from({ length: ncol }, (_, ci) => new TableCell({
        borders, width: { size: widths[ci], type: WidthType.DXA },
        shading: ri === 0 ? { fill: 'E8EEF7', type: ShadingType.CLEAR, color: 'auto' } : undefined,
        margins: { top: 40, bottom: 40, left: 80, right: 80 },
        children: [new Paragraph({ spacing: { line: 240 }, children: runs((r[ci] || '').trim(), { size: 22, bold: ri === 0 ? true : undefined }) })],
      })),
    })),
  });
}
function caption(kind, num, text) {
  return new Paragraph({ alignment: AlignmentType.CENTER, keepNext: kind === 'Хүснэгт', spacing: { before: 120, after: 120 },
    children: [new TextRun({ text: `${kind} ${num}  `, bold: true, font: FONT, size: 22 }), ...runs(text, { size: 22, italics: true })] });
}

// ---------- cover ----------
const cover = [];
cover.push(new Paragraph({ alignment: AlignmentType.LEFT, children: [
  new ImageRun({ type: 'png', data: fs.readFileSync(logoPath), transformation: { width: 80, height: 80 } }),
  new TextRun({ text: '\tШИНЭ МОНГОЛ ТЕХНОЛОГИЙН КОЛЛЕЖ', bold: true, font: FONT, size: 28 })] , tabStops: [{ type: TabStopType.LEFT, position: 1700 }] }));
cover.push(new Paragraph({ indent: { left: 1700 }, spacing: { after: 600 }, children: [new TextRun({ text: 'КОМПЬЮТЕРЫН УХААНЫ ТЭНХИМ', bold: true, font: FONT, size: 28 })] }));
const info = fs.readFileSync(path.join(path.dirname(logoPath), '..', 'Information.tex'), 'utf8');
const val = (k) => (info.match(new RegExp('\\\\newcommand\\{\\\\' + k + '\\}\\{([^}]*)\\}')) || [, ''])[1];
cover.push(new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: 'Оюутны код: ' + val('studentID'), font: FONT, size: SIZE })] }));
cover.push(new Paragraph({ alignment: AlignmentType.RIGHT, spacing: { after: 2400 }, children: [new TextRun({ text: 'Оюутны овог нэр: ' + val('authorsname'), font: FONT, size: SIZE })] }));
cover.push(center(val('titlename'), { bold: true, size: 30, after: 120 }));
cover.push(center('/ДЭД БАКАЛАВРЫН ТӨГСӨЛТИЙН СУДАЛГААНЫ АЖИЛ/', { after: 1200 }));
cover.push(center('Удирдагч багш: /' + val('supervisorname') + ', Бакалавр/', { after: 60 }));
cover.push(center('Гүйцэтгэсэн оюутан: /' + val('studentID') + ', ' + val('authorShort') + '/', { after: 3000 }));
cover.push(center(val('cityname')));
cover.push(center(val('gradYear') + ' он'));
cover.push(center('Багшид үзүүлэх ноорог — Word хувилбар (LaTeX эх бичвэрээс хөрвүүлсэн, ' + new Date().toISOString().slice(0, 10) + ')', { size: 18, before: 400 }));

// ---------- TOC + acronyms ----------
const front = [new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: 'Агуулга', font: FONT })] , pageBreakBefore: false }),
  new TableOfContents('Агуулга', { hyperlink: true, headingStyleRange: '1-3' }),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: 'Товчилсон үгсийн жагсаалт', font: FONT })] })];
const acro = fs.readFileSync(acroPath, 'utf8').split(/\r?\n/).filter(l => !l.trim().startsWith('%')).join('\n');
for (const m of acro.matchAll(/\\acro\{([^}]+)\}\{([^}]+)\}/g)) {
  front.push(new Paragraph({ spacing: { line: LINE }, tabStops: [{ type: TabStopType.LEFT, position: 1400 }],
    children: [new TextRun({ text: m[1], bold: true, font: FONT, size: SIZE }), new TextRun({ text: '\t' + m[2].replace(/--/g, '–'), font: FONT, size: SIZE })] }));
}

// ---------- body ----------
const bodyKids = [];
let i = 0, list = null;
const numberingRefs = [];
let listCounter = 0;
while (i < md.length) {
  let line = md[i];
  if (!line.trim()) { i++; list = null; continue; }
  if (line.startsWith('# ')) { i++; continue; }
  let m;
  if ((m = line.match(/^(#{2,4}) (.*)$/))) {
    const level = m[1].length - 1;
    const h = [HeadingLevel.HEADING_1, HeadingLevel.HEADING_2, HeadingLevel.HEADING_3][level - 1];
    bodyKids.push(new Paragraph({ heading: h, pageBreakBefore: level === 1, children: [new TextRun({ text: m[2], font: FONT })] }));
    i++; list = null; continue;
  }
  if ((m = line.match(/^\*\*(Хүснэгт|Зураг) (\d+\.\d+)\. (.*)\*\*$/))) {
    const [, kind, num, cap] = m;
    if (kind === 'Хүснэгт') {
      bodyKids.push(caption(kind, num, cap));
      i++;
      while (i < md.length && !md[i].trim()) i++;
      const rows = [];
      while (i < md.length && md[i].startsWith('|')) {
        if (!/^\|\s*-/.test(md[i])) rows.push(md[i].replace(/^\|\s?/, '').replace(/\s?\|\s*$/, '').split(' | '));
        i++;
      }
      if (rows.length) bodyKids.push(table(rows));
      bodyKids.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
    } else {
      const f = FIGS[num];
      if (f && fs.existsSync(path.join(figDir, f + '.png'))) bodyKids.push(image(path.join(figDir, f + '.png')));
      bodyKids.push(caption(kind, num, cap));
      i++;
      while (i < md.length && (!md[i].trim() || md[i].startsWith('Зурагт буй бичвэр:'))) i++;
    }
    list = null; continue;
  }
  if ((m = line.match(/^\$\$(.*)\$\$$/))) {
    bodyKids.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 120 },
      children: [new TextRun({ text: latexToText(m[1]) + '        (2.1)', italics: true, font: FONT, size: SIZE })] }));
    i++; continue;
  }
  if ((m = line.match(/^(1\.|-) (.*)$/))) {
    const numbered = m[1] === '1.';
    if (!list || list.numbered !== numbered) {
      listCounter++;
      list = { numbered, ref: numbered ? 'num' + listCounter : 'bullet' };
      if (numbered) numberingRefs.push(list.ref);
    }
    bodyKids.push(new Paragraph({ numbering: { reference: list.ref, level: 0 }, alignment: AlignmentType.JUSTIFIED,
      spacing: { line: LINE, after: 60 }, children: runs(m[2]) }));
    i++; continue;
  }
  if (line.startsWith('|')) { i++; continue; }
  bodyKids.push(body(line));
  list = null; i++;
}

// ---------- bibliography ----------
const bbl = fs.readFileSync(bblPath, 'utf8');
const bib = [new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: true, children: [new TextRun({ text: 'Ном зүй', font: FONT })] })];
const items = bbl.split('\\bibitem').slice(1);
items.forEach((it, k) => {
  const key = (it.match(/^\{([^}]+)\}/) || [])[1];
  let txt = it.replace(/^\{[^}]+\}/, '').replace(/\\end\{thebibliography\}/, '').replace(/\\newblock/g, ' ')
    .replace(/\\url\{([^}]*)\}/g, '$1').replace(/\\href\{([^}]*)\}\{([^}]*)\}/g, '$2 ($1)')
    .replace(/\{\\em ([^}]*)\}/g, '$1').replace(/\\'\{?([a-zA-Z])\}?/g, (a, c) => ({ e: 'é', a: 'á', o: 'ó', i: 'í', u: 'ú', E: 'É' }[c] || c))
    .replace(/\\"\{?([a-zA-Z])\}?/g, (a, c) => ({ o: 'ö', u: 'ü', a: 'ä' }[c] || c)).replace(/\\&/g, '&').replace(/\\_/g, '_')
    .replace(/~/g, ' ').replace(/--/g, '–').replace(/\\[a-zA-Z]+\s?/g, '').replace(/[{}]/g, '').replace(/\s+/g, ' ').trim();
  const n = cite[key] || k + 1;
  bib.push(new Paragraph({ spacing: { line: 276, after: 100 }, indent: { left: 567, hanging: 567 }, children: [new TextRun({ text: `[${n}]\t${txt}`, font: FONT, size: 22 })] }));
});

const numberingConfig = [{ reference: 'bullet', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
  ...numberingRefs.map(ref => ({ reference: ref, levels: [{ level: 0, format: LevelFormat.DECIMAL, text: '%1.', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] }))];

const doc = new Document({
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: SIZE } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 28, bold: true, color: '000000' }, paragraph: { spacing: { before: 240, after: 240 }, keepNext: true, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 26, bold: true, color: '000000' }, paragraph: { spacing: { before: 240, after: 120 }, keepNext: true, outlineLevel: 1 } },
      { id: 'Heading3', name: 'Heading 3', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { font: FONT, size: 24, bold: true, color: '000000' }, paragraph: { spacing: { before: 180, after: 120 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: { config: numberingConfig },
  sections: [
    { properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1701, right: 850 } } }, children: cover },
    { properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1701, right: 850 }, pageNumbers: { start: 1 } } },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 22 })] })] }) },
      children: [...front.slice(1), ...bodyKids, ...bib] },
  ],
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(outPath, buf); console.log('wrote', outPath, bodyKids.length, 'blocks,', items.length, 'refs'); });
