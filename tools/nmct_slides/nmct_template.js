// ШМТК (New Mongol College of Technology) slide template for pptxgenjs.
// Measured from the college lecture template (lekts_4.pdf, 2026):
//   A4 landscape 11.69 x 8.27 in; Times New Roman; title 20pt bold upper-case 0E3199
//   with a 05A0EA rule under it; wide logo top-right; body 17pt; tables Arial 16pt;
//   footnote italic 13pt 333333; page number 11pt 666666 bottom-right.
// Teacher's rule: building background ONLY on the first slide; other slides plain
// white with the logo; closing slide is a summary slide (not photos + "Thank you").
const path = require("path");
const fs = require("fs");

const ASSETS = path.join(__dirname, "assets");
const img = (f) => "image/" + (f.endsWith(".png") ? "png" : "jpeg") + ";base64," +
  fs.readFileSync(path.join(ASSETS, f)).toString("base64");

const COLORS = { navy: "0E3199", rule: "05A0EA", text: "000000", note: "333333",
  pageNo: "666666", red: "C0392B", peach: "FBE3D6", soft: "F2F5FB", white: "FFFFFF" };
const THEME = {
  name: "NMCT lecture",
  headFontFace: "Times New Roman",
  bodyFontFace: "Times New Roman",
  colors: { dk1: "000000", lt1: "FFFFFF", dk2: COLORS.navy, lt2: COLORS.soft,
    accent1: COLORS.navy, accent2: COLORS.rule, accent3: COLORS.red, accent4: "1F7A63",
    accent5: "7F8C8D", accent6: COLORS.peach, hlink: COLORS.navy, folHlink: "5B2C83" },
};
const W = 11.69, H = 8.27, MX = 0.71;

function setup(pres) {
  pres.defineLayout({ name: "A4_LANDSCAPE", width: W, height: H });
  pres.layout = "A4_LANDSCAPE";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  const logo = img("logo_wide.png");
  pres.defineSlideMaster({
    title: "NMCT_COVER",
    background: { color: "FCFDFF" },
    objects: [{ image: { data: img("building_bg.jpg"), x: 0, y: 0.86, w: W, h: 6.57 } }],
  });
  pres.defineSlideMaster({
    title: "NMCT_CONTENT",
    background: { color: "FFFFFF" },
    objects: [
      { image: { data: logo, x: 9.13, y: 1.19, w: 2.33, h: 0.92 } },
      { placeholder: { options: { name: "title", type: "title", x: MX, y: 1.32, w: 8.2, h: 0.42,
          fontSize: 20, bold: true, color: COLORS.navy, valign: "bottom", align: "left", margin: 0,
          fontFace: "Times New Roman" }, text: "" } },
    ],
    slideNumber: { x: 10.75, y: 7.62, w: 0.6, h: 0.3, fontSize: 11, color: COLORS.pageNo, fontFace: "Times New Roman", align: "right" },
  });
  return { logo, seal: img("seal.png") };
}

// Rule under the title, as long as the title (template: title width + ~0.28in).
function rule(pres, s, title) {
  const w = Math.min(8.2, Math.max(1.6, title.length * 0.194 + 0.28));
  s.addShape(pres.shapes.LINE, { x: MX, y: 1.77, w, h: 0, line: { color: COLORS.rule, width: 2 }, objectName: "titleRule" });
}

const txt = (s, t, o) => s.addText(t, Object.assign({ isTextBox: true, margin: 0, fontFace: "Times New Roman",
  fontSize: 17, color: COLORS.text }, o));

function cover(pres, A, { subject, topic, date, notes }) {
  const s = pres.addSlide({ masterName: "NMCT_COVER" });
  s.addImage({ data: A.seal, x: 5.26, y: 1.5, w: 1.15, h: 1.25, objectName: "seal" });
  txt(s, "ШИНЭ МОНГОЛ\nТЕХНОЛОГИЙН КОЛЛЕЖ", { x: 1, y: 3.05, w: W - 2, h: 1.3, fontSize: 40, color: COLORS.navy, align: "center", valign: "middle", objectName: "college" });
  txt(s, subject, { x: 1, y: 4.55, w: W - 2, h: 0.55, fontSize: 30, align: "center", objectName: "subject" });
  txt(s, topic, { x: 0.8, y: 5.65, w: W - 1.6, h: 0.9, fontSize: 24, align: "center", valign: "middle", objectName: "topic" });
  txt(s, date, { x: 1, y: 6.85, w: W - 2, h: 0.35, fontSize: 15, align: "center", objectName: "date" });
  if (notes) s.addNotes(notes);
  return s;
}

function content(pres, title, { lead, footnote, notes } = {}) {
  const s = pres.addSlide({ masterName: "NMCT_CONTENT" });
  s.addText(title.toUpperCase(), { placeholder: "title" });
  rule(pres, s, title);
  if (lead) txt(s, lead, { x: MX, y: 2.05, w: 10.2, h: 0.4, objectName: "lead" });
  if (footnote) txt(s, footnote, { x: MX, y: 6.95, w: 9.8, h: 0.35, fontSize: 13, italic: true, color: COLORS.note, objectName: "footnote" });
  if (notes) s.addNotes(notes);
  return s;
}

// Table in the template's style: black 1pt grid, Arial 16, no header fill.
function table(s, rows, opt) {
  const data = rows.map((r, i) => r.map((c) => {
    const cell = typeof c === "object" && c !== null && !Array.isArray(c) ? c : { text: String(c) };
    cell.options = Object.assign({ fontFace: "Arial", fontSize: opt.fontSize || 16, color: COLORS.text, valign: "middle",
      border: { type: "solid", pt: 1, color: "000000" }, margin: [3, 6, 3, 6], bold: i === 0 && opt.headerBold !== false }, cell.options || {});
    return cell;
  }));
  s.addTable(data, Object.assign({ x: MX, autoPage: false }, opt));
}

const checkList = (items) => items.map((t, i) => ({ text: t, options: { bullet: { code: "2751" }, breakLine: i < items.length - 1 } }));

// Closing slide: one-sentence takeaway + measured points + next step + small thanks/motto/contact.
function closing(pres, A, { headline, points, next, ask, notes }) {
  const s = pres.addSlide({ masterName: "NMCT_CONTENT" });
  s.addText("ДҮГНЭЛТ", { placeholder: "title" });
  rule(pres, s, "ДҮГНЭЛТ");
  txt(s, headline, { x: MX, y: 2.05, w: 10.2, h: 0.85, fontSize: 22, bold: true, color: COLORS.navy, valign: "top", objectName: "headline" });
  txt(s, checkList(points), { x: MX, y: 3.05, w: 6.3, h: 2.2, fontSize: 17, paraSpaceAfter: 8, valign: "top", objectName: "points" });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.35, y: 3.05, w: 3.6, h: 1.75, fill: { color: COLORS.soft }, line: { color: "000000", width: 1 }, objectName: "nextBox" });
  txt(s, [{ text: "Дараагийн алхам", options: { bold: true, color: COLORS.navy, breakLine: true } },
    ...next.map((t, i) => ({ text: t, options: { bullet: { type: "number" }, breakLine: i < next.length - 1 } }))],
    { x: 7.55, y: 3.2, w: 3.25, h: 1.5, fontSize: 15, paraSpaceAfter: 4, valign: "top", objectName: "next" });
  s.addShape(pres.shapes.LINE, { x: MX, y: 5.6, w: 10.25, h: 0, line: { color: COLORS.rule, width: 1 }, objectName: "sep" });
  s.addImage({ data: A.seal, x: MX, y: 5.82, w: 0.62, h: 0.68, objectName: "sealSmall" });
  txt(s, [{ text: "БАЯРЛАЛАА", options: { bold: true, color: COLORS.navy, fontSize: 24, breakLine: true } },
    { text: ask, options: { fontSize: 15, color: COLORS.text } }], { x: 1.5, y: 5.78, w: 5.4, h: 0.8, valign: "middle", objectName: "thanks" });
  txt(s, [{ text: "«Өөрийн гараар улсаа бүтээнэ»", options: { italic: true, breakLine: true } },
    { text: "Компьютерын ухааны тэнхим · nmct.edu.mn" }], { x: 6.9, y: 5.82, w: 4.05, h: 0.7, fontSize: 13, color: COLORS.note, align: "right", valign: "middle", objectName: "motto" });
  if (notes) s.addNotes(notes);
  return s;
}

// Full-page thank-you slide (replaces the old "3 photos + БАЯРЛАЛАА" page).
// Building photo fills the whole page, seal, large БАЯРЛАЛАА, question invite, motto.
function thanks(pres, A, { ask = "Танд ямар асуулт байна вэ?", notes } = {}) {
  const s = pres.addSlide();
  s.background = { color: "FCFDFF" };
  s.addImage({ data: img("building_bg.jpg"), x: 0, y: 0, w: W, h: H, sizing: { type: "cover", w: W, h: H }, objectName: "fullBg" });
  s.addImage({ data: A.seal, x: (W - 1.4) / 2, y: 1.35, w: 1.4, h: 1.52, objectName: "seal" });
  txt(s, "БАЯРЛАЛАА", { x: 1, y: 3.15, w: W - 2, h: 1.0, fontSize: 54, bold: true, color: COLORS.navy, align: "center", valign: "middle", objectName: "thanks" });
  txt(s, ask, { x: 1, y: 4.25, w: W - 2, h: 0.5, fontSize: 22, align: "center", objectName: "ask" });
  s.addShape(pres.shapes.LINE, { x: (W - 3) / 2, y: 5.05, w: 3, h: 0, line: { color: COLORS.rule, width: 2 }, objectName: "rule" });
  txt(s, "«Өөрийн гараар улсаа бүтээнэ»", { x: 1, y: 5.3, w: W - 2, h: 0.45, fontSize: 18, italic: true, color: COLORS.navy, align: "center", objectName: "motto" });
  txt(s, "Шинэ Монгол Технологийн Коллеж · Компьютерын ухааны тэнхим · nmct.edu.mn", { x: 1, y: 6.55, w: W - 2, h: 0.4, fontSize: 14, color: COLORS.note, align: "center", objectName: "footer" });
  if (notes) s.addNotes(notes);
  return s;
}

module.exports = { THEME, COLORS, W, H, MX, setup, cover, content, closing, thanks, table, txt, checkList };
