"""answer_presentation.py: plain wording after the guards, no fact added (2026-11-22)."""
import unittest

from answer_presentation import clean_text, direct_first, plain_note, present

DEPARTMENT = ('Нүүр Тэнхимүүд Химийн инженерийн тэнхим Тэнхим Химийн инженерийн тэнхим Тэнхимийн эрхлэгч : Д.Алтанзул '
              'Хөтөлбөр, төлөвлөгөө Холбоо барих 0 хөтөлбөр 8 багш Тэнхимийн тухай Хөтөлбөр, сургалтын төлөвлөгөө '
              'Багш нар 8 Амжилт Эрхэм зорилго Химийн инженерийн тэнхим нь 5 үндсэн багштай.')
CONTACT = ('Хаяг мэдээлэл Хаяг Улаанбаатар хот, Баянзүрх дүүрэг, 25-р хороо Утас +976 75777799 Имэйл info@nmct.edu.mn '
           'Ажлын цаг Даваа - Баасан: 09:00 - 18:00 Бямба: 10:00 - 14:00 Ням: Амарна Мэдэгдэл илгээх Нэр * Имэйл * '
           'Утас Сэдэв * Сонгоно уу Элсэлтийн мэдээлэл Бусад Мэдэгдэл * Илгээх')


class CleanTextTests(unittest.TestCase):
    def test_department_header_becomes_the_head_and_the_mission(self):
        self.assertEqual(clean_text(DEPARTMENT),
                         'Химийн инженерийн тэнхимийн эрхлэгч: Д.Алтанзул.\n\n'
                         'Эрхэм зорилго: Химийн инженерийн тэнхим нь 5 үндсэн багштай.')

    def test_contact_block_lines_and_the_unconfirmed_website_hours(self):
        kept = clean_text(CONTACT)
        self.assertEqual(kept.split('\n')[:3], ['Хаяг: Улаанбаатар хот, Баянзүрх дүүрэг, 25-р хороо',
                                                'Утас: +976 75777799', 'Имэйл: info@nmct.edu.mn'])
        self.assertIn('Ажлын цаг: Даваа - Баасан: 09:00 - 18:00', kept)
        self.assertNotIn('Мэдэгдэл илгээх', kept)
        # The school confirmed 08:00–17:00 (11/19): the website's 09:00–18:00 is not shown then.
        self.assertNotIn('09:00', clean_text(CONTACT, keep_website_hours=False))

    def test_markers_menus_icons_and_numbered_cards(self):
        self.assertEqual(clean_text('Бүх мэдээ Мэдээ, мэдээлэл Гадаад харилцаа 2026 оны мэдээ. [1]'),
                         'Гадаад харилцаа 2026 оны мэдээ.')
        self.assertEqual(clean_text('Оюутны амьдрал Оюутны Зөвлөл Оюутны зөвлөл нь эрх ашгийг хамгаална. '
                                    '🏛️ Оюутны Зөвлөл 🎯 Клуб & Дугуйлан 🔬 Эрдэм Шинжилгээ Дараа нь'),
                         'Оюутны зөвлөл нь эрх ашгийг хамгаална. Эрдэм Шинжилгээ Дараа нь')
        self.assertEqual(clean_text('Шаардлагууд 01 Идэвхтэй 02 Голч дүн дундаас дээш 03 Япон хэлний N2 түвшин'),
                         'Шаардлагууд\n• Идэвхтэй\n• Голч дүн дундаас дээш\n• Япон хэлний N2 түвшин')

    def test_shouting_line_in_normal_case_with_acronyms(self):
        self.assertEqual(clean_text('БИЧГИЙН ШАЛГАЛТ 10:00 ЦАГААС ЭХЛЭХ ТУЛ ШМТК-ИЙН 1 ДАВХАРТ ИРНЭ.'),
                         'Бичгийн шалгалт 10:00 цагаас эхлэх тул ШМТК-ийн 1 давхарт ирнэ.')
        self.assertEqual(clean_text('ШМТК ирнэ'), 'ШМТК ирнэ')  # short: unchanged

    def test_extract_header_and_roster_wording(self):
        extract = ('2026-2027 оны журам (татсан: 2026-10-10)\n\nЭнэ заалтад төлбөрийг жилээр заасан. — эхийн мэдээлэл:'
                   '\n\nЭлсэх эрхийг бусдад шилжүүлэхийг хориглоно.')
        self.assertEqual(clean_text(extract), 'Элсэх эрхийг бусдад шилжүүлэхийг хориглоно.\n\n'
                                              'Энэ заалтад төлбөрийг жилээр заасан.')
        roster = 'Механик инженерийн тэнхим — сайтад нийтэлсэн багш, ажилтан (2 нэр): Билгүүн (эрхлэгч); Ганбаяр (багш).'
        self.assertEqual(clean_text(roster), 'Механик инженерийн тэнхимийн багш, ажилтан (2): Билгүүн (эрхлэгч); Ганбаяр (багш).')
        self.assertTrue(direct_first('Эрхлэгч нь хэн бэ?', clean_text(roster)).startswith('Билгүүн (эрхлэгч).'))

    def test_no_word_of_the_source_is_changed_otherwise(self):
        sentence = 'Бүртгүүлэгч 500–700 үгтэй эссэ бичиж авч ирнэ.'
        self.assertEqual(clean_text(sentence + ' [1]'), sentence)


class DirectFirstTests(unittest.TestCase):
    def test_the_asked_field_moves_to_the_top(self):
        text = 'Хаяг: Улаанбаатар\nУтас: +976 75777799\nИмэйл: info@nmct.edu.mn'
        self.assertEqual(direct_first('Сургуулийн имэйл хаяг юу вэ?', text).split('\n')[0], 'Имэйл: info@nmct.edu.mn')
        self.assertEqual(direct_first('Утасны дугаар хэд вэ?', text).split('\n')[0], 'Утас: +976 75777799')
        self.assertEqual(direct_first('Хаяг хаана вэ?', text), text)

    def test_the_head_comes_first_in_a_roster(self):
        roster = ('Механик инженерийн тэнхим — сайтад нийтэлсэн багш, ажилтан (3 нэр): '
                  'Бадамжунай (МИТ-ийн багш); Ганбаяр (МИТ-ийн багш); Билгүүн (МИТ-ийн эрхлэгч).')
        shown = direct_first('Механикийн тэнхимийн эрхлэгч хэн бэ?', roster)
        self.assertTrue(shown.startswith('Билгүүн (МИТ-ийн эрхлэгч).'))
        for name in ('Бадамжунай', 'Ганбаяр'):
            self.assertIn(name, shown)


class ReviewFindingTests(unittest.TestCase):
    """Code review 11/23: year ranges are not phones, codes and acronyms keep their capitals, genitive posts."""

    def test_a_school_year_is_not_a_phone_line(self):
        text = '2026-2027 оны хичээлийн жилийн мэдээлэл\nУтас: 7577-7799'
        self.assertEqual(direct_first('Сургалтын албаны утас хэд вэ?', text).split('\n')[0], 'Утас: 7577-7799')

    def test_codes_and_acronyms_survive_sentence_case(self):
        self.assertEqual(clean_text('ЭЕШ-ЫН ОНОО БОЛОН КУ-2 АНГИЙН N2 ТҮВШНИЙ ШАЛГАЛТЫГ ИЛГЭЭНЭ'),
                         'ЭЕШ-ын оноо болон КУ-2 ангийн N2 түвшний шалгалтыг илгээнэ')

    def test_genitive_post_moves_the_holder_first(self):
        roster = 'Захиргаа: Б.Ажилтан (нягтлан бодогч); Т.Оюун (захирал); С.Туслах (туслах).'
        self.assertTrue(direct_first('Захирлын нэр хэн бэ?', roster).startswith('Т.Оюун (захирал).'))


class NoteTests(unittest.TestCase):
    def test_rule_sentences_go_and_where_to_ask_stays(self):
        referral = 'Лавлах газар: Санхүүгийн алба (8-р давхар, 804 тоот).'
        result = dict(query='Төлбөрөө хэсэгчлэн төлж болох уу?', answer=None, reason_code='selection_not_relevant',
                      message=('Энэ асуултад хариулах мэдээлэл хадгалсан эх сурвалжаас олдсонгүй. '
                               'Ойролцоо үгтэй хамааралгүй хэсгийг хариулт болгож харуулахгүй. ' + referral),
                      referral=dict(text=referral))
        present(result)
        self.assertEqual(result['message'], 'Энэ талаар мэдээлэл олдсонгүй. ' + referral)
        self.assertIn('харуулахгүй', result['audit_message'])

    def test_named_detail_and_years(self):
        self.assertEqual(plain_note(dict(message='Энэ хайлтаар олдсон эхэд хоолны газрын цагийн хуваарь тодорхой '
                                                 'заагаагүй байна. Холбоотой өөр тоо, хугацаагаар орлуулахгүй.')),
                         'Хоолны газрын цагийн хуваарь олдсонгүй.')
        self.assertEqual(plain_note(dict(message='Асуусан 2030 оныг батлах тохирох эх энэ хайлтаар олдсонгүй. '
                                                 'Өөр оны мэдээллээр орлуулахгүй.')), '2030 оны мэдээлэл олдсонгүй.')

    def test_a_phone_request_is_answered_as_a_phone_request(self):
        note = plain_note(dict(query='Захирлын гар утасны дугаар хэд вэ?', reason_code='personal_identifier_outside_scope',
                               message='Энэ сургуулийн мэдээллийн систем хүний регистр, паспорт …'))
        self.assertEqual(note, 'Ажилтны гар утасны дугаарыг энд өгдөггүй.')

    def test_answered_reply_hides_the_rule_note_but_keeps_partial_notices(self):
        full = present(dict(query='q', answer='Жилд 8,280,000 төгрөг.', answer_kind='official_website_extract',
                            message='Албан эхийн хэсгийг үг өөрчлөхгүй үзүүлэв.'))
        self.assertEqual(full['message'], '')
        partial = present(dict(query='q', answer='Хэсэг.', answer_kind='partial_official_website_extract',
                               message='Эхээс асуусан бүх мэдээллийг баталж чадсангүй.'))
        self.assertEqual(partial['message'], 'Эхээс асуусан бүх мэдээллийг баталж чадсангүй.')

    def test_clarifications_greetings_and_help_are_untouched(self):
        question = dict(answer=None, message='Аль оны мэдээлэл хэрэгтэй вэ?', clarification=dict(question='Аль он?'))
        self.assertEqual(present(dict(question))['message'], question['message'])
        hello = dict(answer=None, message='Сайн байна уу!', reason_code='conversation_help')
        self.assertEqual(present(dict(hello))['message'], hello['message'])


if __name__ == '__main__':
    unittest.main()
