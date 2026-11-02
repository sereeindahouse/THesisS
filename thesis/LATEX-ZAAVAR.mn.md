# LaTeX-д хэрхэн бичих вэ — товч заавар

LaTeX бол Word шиг товч дарж засдаг биш, **текст файлд бичээд PDF болгодог** арга. Та `.tex` файлд текстээ бичнэ. Гарчиг, хүснэгт, иш татлагыг жижиг командаар заана. Хадгалахад (Ctrl+S) VS Code PDF-ийг шинэчилнэ. Фонт, захын зай, нүүр хуудсыг загвар өөрөө хийдэг.

## 1. Хаана бичих вэ

| Юу бичих | Файл |
|---|---|
| Нэр, оюутны код, удирдагч | `Information.tex` — `[...]` хэсгийг солино |
| Удиртгал | `Chapters/Chapter1_Introduction.tex` |
| Онол, өмнөх судалгаа | `Chapters/Chapter2_Literature.tex` |
| Арга зүй | `Chapters/Chapter3_Methodology.tex` |
| Үр дүн | `Chapters/Chapter4_Results.tex` |
| Ном зүй | `references.bib` |

`main.tex`-ийг бараг засахгүй. Тэр зөвхөн бүлгүүдийг холбодог.

## 2. Энгийн бичвэр

Энгийнээр бичнэ. Шинэ догол мөр эхлүүлэхдээ нэг хоосон мөр үлдээнэ:

```latex
Whisper бол OpenAI-ийн нээлттэй загвар. Үүнийг олон хэлээр сургасан.

Энэ бол шинэ догол мөр.
```

## 3. Гарчиг

```latex
\section{Дуу танилтын харьцуулалт}      % 4.1 гэх мэт дугаартай гарчиг
\subsection{Whisper}                     % дэд гарчиг
```

## 4. Тодруулах, жагсаалт

```latex
\textbf{тод үг}   \textit{налуу үг}

\begin{itemize}
    \item Эхний зүйл
    \item Хоёр дахь зүйл
\end{itemize}

\begin{enumerate}     % 1, 2, 3 гэж дугаарлана
    \item Нэгдүгээр зорилт
\end{enumerate}
```

## 5. Иш татах

1. `references.bib`-д өгүүллээ нэмнэ (Google Scholar-ийн «Cite → BibTeX»-ийг хуулж болно):

```bibtex
@article{mengke2025khalkha,
  title   = {Transliteration-Aided Transfer Learning for Low-Resource ASR},
  author  = {Mengke, Dalai and Meng, Yan and Mihajlik, P{\'e}ter},
  journal = {Electronics}, year = {2025}
}
```

2. Бичвэртээ `\cite{mengke2025khalkha}` гэж бичнэ. PDF дээр `[3]` гэж гарч, ном зүйд автоматаар орно.

## 6. Хүснэгт

```latex
\begin{table}[H]
\centering
\caption{Хүснэгтийн нэр}
\label{tab:minii}
\begin{tabular}{|l|r|r|}
\hline
Хэмжүүр & Whisper & Gemini \\
\hline
WER & 38.07\% & 40.34\% \\
\hline
\end{tabular}
\end{table}
```

`&` нь баганыг, `\\` нь мөрийг тусгаарлана. Бичвэрт `\tref{tab:minii}` гэвэл «Хүснэгт 4.1» гэж гарна.

## 7. Зураг

Зургаа `Pictures/` хавтсанд хийнэ:

```latex
\begin{figure}[H]
\centering
\includegraphics[width=0.8\textwidth]{Pictures/minii_zurag.png}
\caption{Зургийн тайлбар}
\label{fig:minii}
\end{figure}
```

## 8. Анхаарах тэмдэгтүүд

Эдгээр тэмдэгтийн өмнө `\` тавина: `\%`, `\&`, `\_`, `\#`, `\$`. Жишээ нь `38\%`.

`%`-ийн араас бичсэн зүйл **PDF-д харагдахгүй**. Үүнийг өөртөө тэмдэглэл үлдээхэд хэрэглэнэ:

```latex
% ШАЛГАХ: энэ тоог өгүүллийн хүснэгтээс тулгана
```

## 9. Алдаа гарвал

VS Code-ийн доод талын **Problems** цонхонд мөрийн дугаартай алдаа гарна. Ихэвчлэн:
- `{` хаалтаа хаагаагүй;
- `%`, `&`, `_` тэмдэгтийн өмнө `\` тавиагүй;
- `\cite{...}`-ийн нэр `references.bib`-тэй таараагүй.

Тэр мөрийг засаад дахин хадгална.
