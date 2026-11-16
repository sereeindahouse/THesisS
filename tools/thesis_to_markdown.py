"""Flatten the printed text of thesis/main.tex into one Markdown file for review tools.

Only what the PDF prints is kept: `%` comments and `\\iffalse ... \\fi` blocks are dropped.
Headings get their numbers, `\\ref`/`\\tref`/`\\fref` are resolved to those numbers, tables become
pipe rows and each TikZ figure becomes its caption plus the node labels it draws. This is a reading
aid for reviewers and checkers (same text for every reader); it is not a LaTeX converter.

Usage: python tools/thesis_to_markdown.py [output.md]
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THESIS = ROOT / 'thesis'
CHAPTERS = ['Chapter1_Introduction', 'Chapter2_Literature', 'Chapter3_Methodology',
            'Chapter4_Results', 'Chapter5_Conclusion']


FULL_DRAFT = True   # False: follow the short teacher draft (main_teacher.tex)


def printed(tex):
    """Drop disabled blocks and comments; keep escaped percent signs.

    `\\iffull ... [\\else ...] \\fi` marks text that only the full draft prints (the short
    teacher draft skips it). FULL_DRAFT chooses which draft to follow: the full draft keeps the
    first branch and unwraps `\\fullonly{...}`; the teacher draft (`--teacher`) keeps the
    `\\else` branch and drops `\\fullonly{...}`. A `\\fullinput{Chapters/full/x}` line pulls in a
    file that only the full draft prints.
    """
    def full_only_file(match):
        if not FULL_DRAFT:
            return ''
        return (THESIS / f'{match.group(1)}.tex').read_text(encoding='utf-8')

    tex = re.sub(r'^[ \t]*\\fullinput\{([^}]*)\}[ \t]*$', full_only_file, tex, flags=re.M)
    lines, stack = [], []          # stack entries: True = this level is printed
    for line in tex.splitlines():
        code = re.sub(r'(?<!\\)%.*$', '', line)
        if re.match(r'\s*\\iffalse\b', code):
            stack.append(False)
            continue
        if re.match(r'\s*\\iffull\b', code):
            stack.append(FULL_DRAFT)
            continue
        if stack and re.match(r'\s*\\else\b', code):
            stack[-1] = not stack[-1]
            continue
        if stack and re.match(r'\s*\\fi\b', code):
            stack.pop()
            continue
        if not all(stack) or line.lstrip().startswith('%'):
            continue
        code = re.sub(r'\\fullonly\{((?:[^{}]|\{[^{}]*\})*)\}', r'\1' if FULL_DRAFT else '', code)
        lines.append(code.rstrip())
    return '\n'.join(lines)


def macro_arg(text, start):
    """Return (argument, end index) of the balanced {...} that opens at `start`."""
    depth, index = 0, start
    while index < len(text):
        if text[index] == '{' and text[index - 1] != '\\':
            depth += 1
        elif text[index] == '}' and text[index - 1] != '\\':
            depth -= 1
            if depth == 0:
                return text[start + 1:index], index + 1
        index += 1
    raise ValueError('unbalanced braces')


def inline(text):
    for name, pattern in (('bold', r'\\textbf\{'), ('it', r'\\textit\{'), ('tt', r'\\texttt\{')):
        while True:
            match = re.search(pattern, text)
            if not match:
                break
            arg, end = macro_arg(text, match.end() - 1)
            wrap = {'bold': '**', 'it': '*', 'tt': '`'}[name]
            text = text[:match.start()] + wrap + arg + wrap + text[end:]
    text = re.sub(r'\\acs?\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\cite\{([^}]*)\}', r'[\1]', text)
    text = re.sub(r'\\(allowbreak|centering|hline|noindent)\b\s*', '', text)
    text = re.sub(r'\\cline\{[^}]*\}', '', text)
    text = re.sub(r'\$\\rightarrow\$', '→', text)
    text = re.sub(r'\\(scriptsize|footnotesize|small|itshape|bfseries)\b\s*', '', text)
    text = text.replace('\\%', '%').replace('\\$', '$').replace('\\&', '&').replace('~', ' ')
    text = text.replace('\\\\', ' / ')
    return text


def figure_text(name):
    """Node labels of a TikZ figure, in file order (what the reader sees in the drawing)."""
    source = printed((THESIS / 'Figures' / f'{name}.tex').read_text(encoding='utf-8'))
    labels = []
    # actors drawn with the figure's own \stickman{name}{position}{label} macro
    for match in re.finditer(r'^\\stickman\{[^}]*\}\{[^}]*\}(?=\{)', source, flags=re.M):
        label, _ = macro_arg(source, match.end())
        labels.append(re.sub(r'\s+', ' ', re.sub(r'[{}]', '', inline(label))).strip(' /'))
    source = re.sub(r'\\newcommand\{\\stickman\}.*?\n\}\n', '', source, flags=re.S)
    for match in re.finditer(r'\\node\b[^;]*?;', source, flags=re.S):
        chunk = match.group(0)
        brace = chunk.rfind('{', 0, chunk.rfind('}') + 1)
        # last balanced group of the statement is the label
        depth, end = 0, None
        for index in range(len(chunk) - 1, -1, -1):
            if chunk[index] == '}':
                depth += 1
                end = end if end is not None else index
            elif chunk[index] == '{':
                depth -= 1
                if depth == 0:
                    brace = index
                    break
        if end is None:
            continue
        label = inline(chunk[brace + 1:end])
        label = re.sub(r'\\nodepart\{second\}', ':', label)
        label = re.sub(r'[{}]', '', label)
        label = re.sub(r'\s+', ' ', label).strip(' /')
        if label and '#' not in label:
            labels.append(label)
    return labels


def convert():
    numbers, out = {}, []
    chapter = section = subsection = table = figure = equation = 0
    bodies = [printed((THESIS / 'Chapters' / f'{name}.tex').read_text(encoding='utf-8')) for name in CHAPTERS]

    # pass 1: numbers for labels
    for body in bodies:
        current = None
        for line in body.splitlines():
            if match := re.match(r'\\chapter\{(.*)\}', line):
                chapter += 1
                section = subsection = table = figure = equation = 0
                current = str(chapter)
            elif match := re.match(r'\\section\{(.*)\}', line):
                section += 1
                subsection = 0
                current = f'{chapter}.{section}'
            elif match := re.match(r'\\subsection\{(.*)\}', line):
                subsection += 1
                current = f'{chapter}.{section}.{subsection}'
            elif re.match(r'\\begin\{table\}', line):
                table += 1
                current = f'{chapter}.{table}'
            elif re.match(r'\\begin\{figure\}', line):
                figure += 1
                current = f'{chapter}.{figure}'
            elif re.match(r'\\begin\{equation\}', line):
                equation += 1
                current = f'{chapter}.{equation}'
            for label in re.findall(r'\\label\{([^}]*)\}', line):
                numbers[label] = current

    def refs(text):
        text = re.sub(r'\\tref\{([^}]*)\}', lambda m: f'Хүснэгт {numbers.get(m.group(1), "??")}', text)
        text = re.sub(r'\\fref\{([^}]*)\}', lambda m: f'Зураг {numbers.get(m.group(1), "??")}', text)
        return re.sub(r'\\ref\{([^}]*)\}', lambda m: numbers.get(m.group(1), '??'), text)

    info = printed((THESIS / 'Information.tex').read_text(encoding='utf-8'))
    title = re.search(r'\\newcommand\{\\titlename\}\{(.*)\}', info).group(1)
    out.append(f'# {title}\n')

    chapter = section = subsection = table = figure = 0
    for body in bodies:
        lines = body.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            index += 1
            if match := re.match(r'\\chapter\{(.*)\}', line):
                chapter += 1
                section = subsection = table = figure = 0
                out.append(f'\n## {chapter}. {match.group(1)}\n')
            elif match := re.match(r'\\section\{(.*)\}', line):
                section += 1
                subsection = 0
                out.append(f'\n### {chapter}.{section}. {match.group(1)}\n')
            elif match := re.match(r'\\subsection\{(.*)\}', line):
                subsection += 1
                out.append(f'\n#### {chapter}.{section}.{subsection}. {match.group(1)}\n')
            elif re.match(r'\\begin\{(table|figure)\}', line):
                kind = 'table' if 'table' in line else 'figure'
                block = []
                while not re.match(r'\\end\{(table|figure)\}', lines[index]):
                    block.append(lines[index])
                    index += 1
                index += 1
                text = '\n'.join(block)
                caption = inline(refs(re.search(r'\\caption\{(.*)\}', text).group(1)))
                if kind == 'table':
                    table += 1
                    out.append(f'\n**Хүснэгт {chapter}.{table}. {caption}**\n')
                    rows = text[text.index('\\begin{tabular}'):text.index('\\end{tabular}')]
                    rows = rows.split('\n', 1)[1]
                    rows = re.sub(r'\\multirow\{[^}]*\}\{[^}]*\}\{([^}]*)\}', r'\1', rows)
                    rows = re.sub(r'\\multicolumn\{[^}]*\}\{[^}]*\}\{((?:[^{}]|\{[^{}]*\})*)\}', r'\1', rows)
                    for row in rows.split('\\\\'):
                        cells = [re.sub(r'\s+', ' ', inline(refs(cell))).strip() for cell in row.split('&')]
                        if any(cells):
                            out.append('| ' + ' | '.join(cells) + ' |')
                    out.append('')
                else:
                    figure += 1
                    out.append(f'\n**Зураг {chapter}.{figure}. {caption}**\n')
                    if name := re.search(r'\\input\{Figures/([^}]*)\}', text):
                        out.append('Зурагт буй бичвэр: ' + '; '.join(figure_text(name.group(1))) + '\n')
            elif re.match(r'\\begin\{equation\}', line):
                block = []
                while not re.match(r'\\end\{equation\}', lines[index]):
                    block.append(lines[index])
                    index += 1
                index += 1
                out.append('$$' + ' '.join(b for b in block if not b.startswith('\\label')) + '$$')
            elif re.match(r'\\(begin|end)\{(enumerate|itemize)\}', line) or re.match(r'\\label\{', line):
                continue
            elif match := re.match(r'\s*\\item\s+(.*)', line):
                out.append('- ' + inline(refs(match.group(1))))
            else:
                out.append(inline(refs(line)))
    text = '\n'.join(out)
    return re.sub(r'\n{3,}', '\n\n', text).strip() + '\n'


if __name__ == '__main__':
    args = [arg for arg in sys.argv[1:] if arg != '--teacher']
    FULL_DRAFT = '--teacher' not in sys.argv[1:]
    target = Path(args[0]) if args else ROOT / 'runtime' / 'thesis-manuscript.md'
    markdown = convert()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding='utf-8', newline='\n')
    print(f'{target} · {len(markdown.split())} words · unresolved refs: {markdown.count("??")}')
