# Халх Монгол ASR — аргын нягтлал, 2026.10.10

Эх: Dalai Mengke, Yan Meng, Péter Mihajlik (2025), Transliteration-Aided Transfer Learning for Low-Resource ASR: A Case Study on Khalkha Mongolian. [DOI/publisher](https://doi.org/10.3390/electronics14061137). Publisher endpoint 429 алдаатай байсан тул [MDPI-ээс өгсөн full-text copy](https://www.researchgate.net/publication/389867217_Transliteration-Aided_Transfer_Learning_for_Low-Resource_ASR_A_Case_Study_on_Khalkha_Mongolian)-ийн §2.2, §3.1–3.2, §4.1–4.5, §5 ба Хүснэгт 1, §6-ийн текстийг нягталсан. Хэрэглэгч энэ өгүүллийг уншиж дууссан гэж бүртгэхгүй; бүх зураг/туршилтыг дахин хэрэгжүүлээгүй.

Арга нь хоёр шатны fine-tuning: Чахар өгөгдлийн бичвэрийг кириллд хөрвүүлж эхний нэмэлт сургалт; дараа нь Халх өгөгдлөөр тохируулан сургалт. Зохиогчид §3.1-д M2ASR-MONGO-ийн 147 цаг train/9.5validation/6.1test, Common Voice17-ийн 3 цаг train/2.7validation/3test гэж тайлагнасан. Энэ нь «олон видео байхад болно» гэсэн арга биш; аудио–бичвэрийн хос, зорилтот аялга ба тусдаа үнэлгээ шаардсан туршилт.

Хүснэгт 1-д Whisper-large-v3-ын WER zero-shot92.60, DFT43.02, TFT31.45 гэж тайлагнасан; эдгээр нь тэдний CV17 тест, манай нэг хүний development WAV биш. Манай score бага байсан ч шууд илүү модель хийсэн гэж дүгнэхгүй. Дата/code/checkpoint-ийг олж давтан туршаагүй; энэ аргыг манай project-д хэрэгжүүлсэн гэж хэлэхгүй.

Техникийн тодруулах зүйл: §3.2 Whisper-д CTC loss хэрэглэсэн гэж бичсэн нь стандарт Hugging Face WhisperForConditionalGeneration-ийн autoregressive CrossEntropyLoss-тай зөрж байна. Локал Transformers4.57.6 modeling_whisper.py:1311–1314 болон [албан ёсны pinned source](https://github.com/huggingface/transformers/blob/v4.57.6/src/transformers/models/whisper/modeling_whisper.py)-ийг шалгасан. Зохиогчийн өөрчилсөн кодгүйгээр CTC гэсэн тайлбарыг implementation заавар болгохгүй; редакцийн алдаа эсвэл тайлагнаагүй өөрчлөлт эсэхийг тогтоогоогүй.

Манай шийдвэр: судалгааны үндэслэл болгон ашиглана, эцсийн roadmap-д байхгүй өөрийн fine-tuning ажлыг нэмж эхлүүлэхгүй. Бэлэн Монгол модель сонгох ба бодит алдааг хэмжих ажил үргэлжилнэ.
