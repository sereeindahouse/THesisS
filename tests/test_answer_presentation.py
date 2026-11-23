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
                                              'Энэ заалтад төлбөрийг жилээр заасан.\n\n'
                                              '(Эх сурвалж: 2026-2027 оны журам, 2026-10-10)')
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
        # The notice stays (something is missing), in plain words (11/23 (2)).
        self.assertEqual(partial['message'], 'Асуусан мэдээллийн зарим нь олдсонгүй.')
        self.assertEqual(partial['audit_message'], 'Эхээс асуусан бүх мэдээллийг баталж чадсангүй.')
        platform = present(dict(query='q', answer='Хэсэг.', answer_kind='partial_official_website_extract',
                                message='Эхэд платформын нэр заагаагүй.'))
        self.assertEqual(platform['message'], 'Платформын нэр олдсонгүй.')

    def test_clarifications_greetings_and_help_are_untouched(self):
        question = dict(answer=None, message='Аль оны мэдээлэл хэрэгтэй вэ?', clarification=dict(question='Аль он?'))
        self.assertEqual(present(dict(question))['message'], question['message'])
        hello = dict(answer=None, message='Сайн байна уу!', reason_code='conversation_help')
        self.assertEqual(present(dict(hello))['message'], hello['message'])


class SecondPassTests(unittest.TestCase):
    """11/23 (2): read like a person — the asked card first, the amount first, notes the first lint missed."""

    def test_the_asked_card_starts_the_answer_and_the_footer_goes(self):
        text = ('Математик 40 оноо\nФизик 20 оноо\nЯрилцлага 20 оноо\nШалгалтаас чөлөөлөгдөх\nОнцгой эрх олгох тохиолдол\n'
                'Олимпиадын шалгаруулалтад орсон сурагч\nЭлсэгч хэн байх вэ\n1-р курс\nХолбоо барих\nЛавлах утас\n'
                'Бүртгэлтэй холбоотой асуултаа доорх дугаараар лавлана уу.')
        shown = present(dict(query='Элсэлтийн шалгалтаас чөлөөлөгдөх боломж бий юу?', answer=text,
                             answer_kind='rag_generated', message=''))['answer']
        self.assertTrue(shown.startswith('Шалгалтаас чөлөөлөгдөх\nОнцгой эрх олгох тохиолдол'))
        self.assertNotIn('Математик', shown)
        self.assertNotIn('Холбоо барих', shown)
        # A line before the asked card that shares a word with the question: nothing before the card goes.
        self.assertTrue(present(dict(query='Элсэлтийн шалгалтаас чөлөөлөгдөх боломж бий юу?',
                                     answer='Шалгалт 2 удаа\n' + text, answer_kind='rag_generated'))['answer']
                        .startswith('Шалгалт 2 удаа\nМатематик 40 оноо'))
        # Asked contacts keep the footer; tables and stored answers are never cut.
        self.assertIn('Холбоо барих', present(dict(query='Элсэлтийн шалгалтаас чөлөөлөгдөх бол хэнтэй холбоо барих вэ?',
                                                    answer=text, answer_kind='rag_generated'))['answer'])
        self.assertIn('Математик', present(dict(query='Элсэлтийн шалгалтаас чөлөөлөгдөх боломж бий юу?', answer=text,
                                                 answer_kind='reception_table_lookup'))['answer'])

    def test_number_cards_read_as_label_value_note(self):
        cards = ('7\nСонгох мэргэжил\n5 шинэ + 2 шилжилт\n8/13\nБүртгэл хаагдах\n16:00 цаг\n20,000₮\nБүртгэлийн хураамж\n'
                 'QPay-ээр төлнө\nХугацааны хуваарь')
        self.assertEqual(clean_text(cards), 'Сонгох мэргэжил: 7 (5 шинэ + 2 шилжилт)\nБүртгэл хаагдах: 8/13 (16:00 цаг)\n'
                                            'Бүртгэлийн хураамж: 20,000₮ (QPay-ээр төлнө)\nХугацааны хуваарь')
        shown = present(dict(query='Элсэлтийн бүртгэл хэдэн цагт хаагдах вэ?', answer=cards, answer_kind='rag_generated'))
        self.assertTrue(shown['answer'].startswith('Бүртгэл хаагдах: 8/13 (16:00 цаг)'))
        # A numbered list is not a card; one card alone is left as it is.
        self.assertEqual(clean_text('1\n1-р курс\nЕБС-ийн 9 дүгээр анги\n2\n2-р курс'), '1\n1-р курс\nЕБС-ийн 9 дүгээр анги\n2\n2-р курс')
        self.assertEqual(clean_text('100%\nСургалтын төлбөр\nЯпон коосэнд'), '100%\nСургалтын төлбөр\nЯпон коосэнд')

    def test_the_asked_amount_and_the_head_alone(self):
        text = ('Ярилцлагаар суралцах сонирхлыг шалгана. Нийт 20 оноогоор дүгнэнэ. Ярилцлагын шалгалт 15 минут үргэлжилнэ.')
        self.assertEqual(direct_first('Ярилцлага хэдэн минут үргэлжлэх вэ?', text),
                         'Ярилцлагын шалгалт 15 минут үргэлжилнэ. Ярилцлагаар суралцах сонирхлыг шалгана. '
                         'Нийт 20 оноогоор дүгнэнэ.')
        self.assertEqual(direct_first('Химийн тэнхимийн эрхлэгч хэн бэ?', clean_text(DEPARTMENT)),
                         'Химийн инженерийн тэнхимийн эрхлэгч: Д.Алтанзул.')
        # The mission stays when it is what was asked.
        self.assertIn('Эрхэм зорилго', direct_first('Химийн тэнхимийн эрхэм зорилго юу вэ?', clean_text(DEPARTMENT)))

    def test_a_japanese_card_label_goes(self):
        self.assertEqual(clean_text('Бэлтгэл хөтөлбөр 合宿 · Гашшүкү хөтөлбөр'), 'Бэлтгэл хөтөлбөр Гашшүкү хөтөлбөр')

    def test_notes_the_first_lint_missed(self):
        referral = 'Лавлах газар: Сургалтын алба (4-р давхар, 406 тоот).'
        for message, reason, lead in (
                ('Асуултын нэр, он, тоо эсвэл хүрээг хамтад нь дэмжих нэг хадгалсан асуулт алга. Тааж нэгтгэхгүй.',
                 'constraints_not_supported_together', 'Энэ талаар мэдээлэл олдсонгүй.'),
                ('Ажлын эсвэл уулзах цаг хүснэгтэд бүртгэгдээгүй байна.', 'reception_hours_unknown',
                 'Ажлын цагийн мэдээлэл олдсонгүй.'),
                ('Асуусан ярилцлагын үргэлжлэх хугацаа энэ хайлтын эхээр хамтад нь баталж чадсангүй.', 'x',
                 'Энэ асуултын хариу олдсонгүй.'),
                ('Нэрлэсэн өрөөг ресепшний хүснэгтээс баталсангүй. Өрөөний бүтэн нэрийг шалгана уу.',
                 'reception_room_not_found', 'Нэрлэсэн өрөө олдсонгүй. Өрөөний дугаарыг шалгаад дахин асууна уу.'),
                ('Асуусан он, хичээлийн жилийг эхээс хайж тогтооно. Хадгалсан богино FAQ-аар бусад талбарыг орлуулахгүй.',
                 'requested_year_value_lookup', 'Энэ талаар мэдээлэл олдсонгүй.')):
            result = present(dict(query='q', answer=None, message=message + ' ' + referral, reason_code=reason,
                                  referral=dict(text=referral)))
            self.assertEqual(result['message'], lead + ' ' + referral)
        # «not found» is said once.
        self.assertEqual(plain_note(dict(message='Асуусан мэдээллийг энэ хайлтын эх сурвалжаас бүрэн баталж чадсангүй. '
                                                 'Энэ нь хадгалсан эхээр батлахгүй.')), 'Асуусан мэдээлэл бүрэн олдсонгүй.')

    def test_the_router_asks_back_in_plain_words(self):
        asked = 'Төстэй асуулт олдлоо. Хариулахын өмнө аль хадгалсан асуултыг хэлж байгааг тодруулъя.'
        result = present(dict(query='q', answer=None, message=asked,
                              clarification=dict(kind='select_supported_question', question=asked, options=[])))
        self.assertEqual(result['clarification']['question'], 'Төстэй хэд хэдэн асуулт байна. Аль нь болохыг доороос сонгоно уу.')
        self.assertEqual(result['message'], result['clarification']['question'])
        self.assertEqual(result['audit_message'], asked)
        # By kind, so a reworded router question is still plain; other kinds are left alone.
        reworded = present(dict(answer=None, message='x', clarification=dict(kind='ambiguous_exact_match', question='Өөр FAQ үг')))
        self.assertEqual(reworded['clarification']['question'], 'Ижил төстэй хэд хэдэн асуулт байна. Аль нь болохыг доороос сонгоно уу.')
        year = present(dict(answer=None, message='Аль он?', clarification=dict(kind='missing_year', question='Аль он?')))
        self.assertEqual(year['clarification']['question'], 'Аль он?')


class ReviewSecondPassTests(unittest.TestCase):
    """/code-review medium on 11/23 (2)."""

    def test_years_and_phones_are_not_number_cards(self):
        text = '2026\nЭлсэлтийн журам\n2025\nЭлсэлтийн журам'
        self.assertEqual(clean_text(text), text)
        self.assertEqual(clean_text('75777799\nСургалтын алба\n00001111\nСанхүүгийн алба'),
                         '75777799\nСургалтын алба\n00001111\nСанхүүгийн алба')

    def test_any_spelling_of_an_email_question_keeps_the_footer(self):
        text = ('Онооны хүснэгт\nМатематик 40 оноо\nШалгалтаас чөлөөлөгдөх тохиолдол\nОлимпиадад орсон сурагч\n'
                'Холбоо барих\nИмэйл: info@nmct.edu.mn')
        for query in ('Шалгалтаас чөлөөлөгдөх талаар и-мэйл хаяг?', 'Шалгалтаас чөлөөлөгдөх бол цахим шуудан юу вэ?'):
            with self.subTest(query=query):
                self.assertIn('info@nmct.edu.mn', present(dict(query=query, answer=text, answer_kind='rag_generated'))['answer'])

    def test_the_head_alone_keeps_the_source_line(self):
        extract = ('Механик тэнхим (татсан: 2026-11-09) — эхийн мэдээлэл:\n\nМеханик инженерийн тэнхимийн эрхлэгч: Б.Билгүүн.'
                   '\n\nЭрхэм зорилго: Инженер бэлтгэнэ.')
        shown = present(dict(query='Механикийн тэнхимийн эрхлэгч хэн бэ?', answer=extract,
                             answer_kind='official_website_extract'))['answer']
        self.assertEqual(shown, 'Механик инженерийн тэнхимийн эрхлэгч: Б.Билгүүн.\n\n(Эх сурвалж: Механик тэнхим, 2026-11-09)')

    def test_a_partial_answer_never_says_nothing_was_found(self):
        partial = present(dict(query='q', answer='Хэсэг.', answer_kind='partial_official_website_extract',
                               message='Асуултын нэрийг энэ багцын хадгалсан асуулттай баттай холбож чадсангүй.'))
        self.assertEqual(partial['message'], 'Асуусан мэдээллийн зарим нь олдсонгүй.')

    def test_advice_stays_and_later_rule_talk_goes(self):
        note = plain_note(dict(message='Асуусан мэдээллийг энэ хайлтын эх сурвалжаас бүрэн баталж чадсангүй. '
                                       'Өөр үйл явдал, он эсвэл ойролцоо мэдээллээр орлуулахгүй. Товчилсон нэр хэрэглэсэн '
                                       'бол бүтэн нэрийг нь бичиж, асуусан оноо хамт тодруулна уу.'))
        self.assertEqual(note, 'Асуусан мэдээлэл бүрэн олдсонгүй. Нэр, оныг бүтнээр нь бичиж дахин асууж болно.')
        fx = plain_note(dict(message='Хадгалсан мэдээ өнөөдрийн валютын ханшийг батлахгүй. Мэдээний ойролцоо хөрвүүлсэн '
                                     'дүнг өнөөдрийн яг ханш гэж орлуулахгүй. Огноотой ханшийг банкны албан эхээс шалгана уу.'))
        self.assertEqual(fx, 'Өнөөдрийн валютын ханшийг банкнаас шалгана уу.')
        self.assertEqual(plain_note(dict(message='Тэтгэлгийн босгыг энэ хайлтаар олж чадсангүй. Утгыг баталсан хуудас алга.')),
                         'Энэ талаар мэдээлэл олдсонгүй. Утгыг баталсан хуудас алга.')

    def test_inflected_school_words_do_not_steer_the_focus(self):
        from answer_presentation import _stems
        self.assertEqual(_stems('Сургуулиас хэдэн хүн элсэх вэ?'), {'элсэх'})

    def test_the_first_strong_line_starts_and_a_counted_line_comes_first(self):
        # «Шалгалтаас чөлөөлөгдөх» (two words) starts, though the olympiad line below it shares three (11/23 (2) probe).
        text = ('Математик 40 оноо\nФизик 20 оноо\nЯрилцлага 20 оноо\nШалгалтаас чөлөөлөгдөх\nОнцгой эрх олгох тохиолдол\n'
                'Аймгийн олимпиад, уралдааны шалгаруулалтад орсон')
        shown = present(dict(query='Олимпиадад орсон бол элсэлтийн шалгалтаас чөлөөлөгдөх үү?', answer=text,
                             answer_kind='rag_generated'))['answer']
        self.assertTrue(shown.startswith('Шалгалтаас чөлөөлөгдөх\n'))
        card = ('Тэтгэлэгт хөтөлбөр\nМонбүшёо — Японы Засгийн газрын тэтгэлэг\nЗардлыг 100% хариуцдаг.\n'
                'Одоогоор 12 оюутан тус тэтгэлэгт хамрагдаад байна.')
        self.assertTrue(direct_first('Монбүшёо тэтгэлэгт хэдэн оюутан хамрагдсан бэ?', card)
                        .startswith('Одоогоор 12 оюутан'))
        # A count already near the top stays where it is.
        self.assertEqual(direct_first('Хэдэн жил суралцдаг вэ?', '1-р курсээс 5 жил суралцана.\nДэд бакалавр олгоно.'),
                         '1-р курсээс 5 жил суралцана.\nДэд бакалавр олгоно.')

    def test_the_source_line_and_a_repeated_question_are_not_spoken(self):
        from answer_contract import spoken_text
        shown = present(dict(query='Сургалтын төлбөр хэд вэ?', answer_kind='official_website_extract',
                             answer='Элсэлт 2026 (татсан: 2026-10-10) — эхийн мэдээлэл:\n\nСургалтын төлбөр: жилд 8,280,000 ₮.'))
        self.assertIn('(Эх сурвалж: Элсэлт 2026, 2026-10-10)', shown['answer'])
        self.assertNotIn('Эх сурвалж', spoken_text(shown))
        asked = 'Аль оны мэдээлэл хэрэгтэй вэ?'
        self.assertEqual(spoken_text(dict(answer=None, message=asked, clarification=dict(question=asked))).count('Аль оны'), 1)

    def test_an_incomplete_timetable_note_claims_no_lesson(self):
        note = plain_note(dict(reason_code='reception_timetable_incomplete', message='Энэ цагт хичээл бүртгэгдээгүй боловч …'))
        self.assertEqual(note, 'Хичээлийн хуваарь бүрэн биш тул хуваариар хариулах боломжгүй.')



class CheckSetPresentationTests(unittest.TestCase):
    """11/23 check set: a reordered answer drops a stray «Тийм.», where to go is answered by the office."""

    def test_a_bare_yes_is_not_left_inside_the_reordered_answer(self):
        text = 'Тийм. Өвлийн амралтаар явна. Компанид 7–30 хоногийн хугацаанд дадлага хийнэ.'
        self.assertEqual(direct_first('Японд дадлагад хэдэн хоног явдаг вэ?', text),
                         'Компанид 7–30 хоногийн хугацаанд дадлага хийнэ. Өвлийн амралтаар явна.')

    def test_where_to_go_is_answered_by_the_office_the_question_names(self):
        referral = 'Лавлах газар: Сургалтын алба (4-р давхар, 406 тоот). Сургуулийн ерөнхий утас +976 75777799.'

        def shown(query, source='question'):
            return present(dict(query=query, answer=None, reason_code='selection_not_relevant',
                                message='Ойролцоо хэсгийг хариулт болгож харуулахгүй. ' + referral,
                                referral=dict(text=referral, office_source=source)))['message']
        for query in ('Ажлын анкет өгөх гэсэн юм, хаана очих вэ?', 'хэддүгээр давхарт гарах вэ?',
                      'Хүүхэд өвдөөд хичээлдээ ирж чадахгүй нь, хэнд хэлэх вэ?'):
            with self.subTest(query=query):
                self.assertEqual(shown(query), referral)
        # An office guessed from related pages, or a question that is not where to go, keeps «not found».
        self.assertEqual(shown('Ажлын анкет өгөх гэсэн юм, хаана очих вэ?', 'source_topic'),
                         'Энэ талаар мэдээлэл олдсонгүй. ' + referral)
        self.assertEqual(shown('Гар утсаа гээчихлээ, олдсон юм хаана хадгалдаг вэ?'),
                         'Энэ талаар мэдээлэл олдсонгүй. ' + referral)

    def test_whom_to_tell_today_is_no_question_about_todays_openings(self):
        referral = 'Лавлах газар: Сургалтын алба (4-р давхар, 406 тоот). Ангийн багшдаа мөн мэдэгдээрэй.'
        result = present(dict(query='Хүүхэд маань өвдөөд өнөөдөр хичээлдээ ирж чадахгүй нь хэнд хэлэх вэ', answer=None,
                              reason_code='live_status_not_supported',
                              message=('Хадгалсан эх нь өнөөдрийн мэдээлэл, бүртгэл, сул орон тооны бодит төлөвийг батлахгүй. '
                                       'Доорх албан эхийн огноог шалгах эсвэл сургуультай холбогдоорой. ' + referral),
                              referral=dict(text=referral, office_source='question')))
        self.assertEqual(result['message'], referral)


if __name__ == '__main__':
    unittest.main()
