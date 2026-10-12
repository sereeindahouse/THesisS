import unittest
from rag_runtime import focused_extract


def source(text,visual=True):
    return dict(url='https://nmct.edu.mn/rules.png' if visual else 'https://nmct.edu.mn/programs/computer-science-program',
                text_scope='document_visual_excerpt' if visual else 'main_element',text=text)


class FocusedDocumentAnswers(unittest.TestCase):
    def test_photo_format_is_not_registration_fee(self):
        photo=source('Сүүлийн 6 сарын цээж зургийг jpeg, png, jpg файлаар оруулна.')
        fee=source('Бүртгэлийн хураамж 20,000 төгрөг.')
        self.assertEqual(focused_extract('Бүртгэлд зургаа ямар форматтай оруулах вэ?',[fee,photo]),(photo,photo['text']))

    def test_photo_color_is_not_inferred(self):
        photo=source('Сүүлийн 6 сарын цээж зургийг jpeg, png, jpg файлаар оруулна.')
        self.assertIsNone(focused_extract('Зургаа өнгөтэй, ямар форматтай өгөх вэ?',[photo]))

    def test_interview_duration_retains_parent_condition(self):
        rule=source('Эцэг эхтэйгээ ярилцлагад орно. Ярилцлагын шалгалт 15 минут үргэлжилнэ.')
        self.assertEqual(focused_extract('Ярилцлага хэдэн минут вэ?',[rule])[1],rule['text'])

    def test_interview_passing_score_not_inferred_from_maximum(self):
        rule=source('Ярилцлага нийт 20 оноо. Ярилцлагын шалгалт 15 минут үргэлжилнэ.')
        self.assertIsNone(focused_extract('Ярилцлагын тэнцэх босго оноо хэд вэ?',[rule]))

    def test_transfer_rights_shows_exact_prohibition(self):
        rule=source('Элсэх эрхийг бусдад шилжүүлэхийг хориглоно.')
        self.assertEqual(focused_extract('Элсэх эрхээ өөр хүнд шилжүүлж болох уу?',[rule])[1],rule['text'])

    def test_olympiad_exemption_keeps_rank_and_program_restriction(self):
        text='Шагналын танилцуулга.\nАмжилттай оролцсон 10 сурагчдад (6-15-р байр) Химийн инженерийн эрхийн бичиг (Химийн инженерээс бусад ангийг сонгох бол үйлчлэхгүй)'
        answer=focused_extract('Хими биологийн олимпиадын эрхийн бичгээр өөр ангид элсэж болох уу?',[source(text)])[1]
        self.assertIn('6-15-р байр',answer)
        self.assertIn('бусад ангийг сонгох бол үйлчлэхгүй',answer)

    def test_programming_language_extract_preserves_exact_line(self):
        text='Хөтөлбөр\nПрограммчлалын хэл (C/C++, Java, Python) ашиглах чадвар\nСүлжээ'
        result=focused_extract('Ямар программчлалын хэл үзэх вэ?',[source(text,False)])
        self.assertEqual(result[1],text.splitlines()[1])

    def test_programming_language_credits_not_inferred(self):
        self.assertIsNone(focused_extract('Программчлалын хэл хэдэн кредит вэ?',[source('C/C++, Java, Python',False)]))


if __name__=='__main__': unittest.main()
