from app.search_passages import evidence_windows, sentences, source_window


def test_chinese_evidence_preserves_source_offsets_and_complete_answer():
    content = '背景。\n\n缓存可以保持有效。定时激活也会收费。最后的补充说明。'
    passage = source_window(content, '激活也会收费')
    assert passage is not None
    assert content[passage.start:passage.end] == passage.text
    quotes = evidence_windows(passage, width=20)
    assert any('定时激活也会收费。' in quote.text for quote in quotes)
    assert all(content[quote.start:quote.end] == quote.text for quote in quotes)


def test_english_sentences_and_newlines_are_preserved():
    content = 'Review the code. Send the feedback.\nThe reviewer did the work.'
    parts = sentences(content)
    assert len(parts) == 3
    assert ''.join(part.text for part in parts) == content
    passage = source_window(content, 'reviewer', width=40)
    assert passage is not None
    assert 'The reviewer did the work.' in passage.text


def test_missing_fragment_is_not_fabricated():
    assert source_window('Only stored words.', 'Made up words') is None


def test_long_sentence_is_not_silently_cut_at_display_width():
    text = '铺垫' * 150 + '费用由发起者承担。'
    passage = source_window(text, '费用由发起者承担。')
    assert passage is not None
    assert any(quote.text.endswith('费用由发起者承担。') for quote in evidence_windows(passage))


def test_quote_keeps_a_question_and_its_following_response_together():
    from app.search_passages import SourcePassage
    text = 'Some background. Who pays the fee? The sender pays it. More details.'
    quotes = evidence_windows(SourcePassage(text, 0, len(text)), width=35)
    assert quotes
    for quote in quotes:
        if 'Who pays the fee?' in quote.text:
            assert 'The sender pays it.' in quote.text
        assert text[quote.start:quote.end] == quote.text


def test_quote_does_not_fill_remaining_space_with_the_next_section():
    from app.search_passages import SourcePassage
    text = '激活缓存需要付费。\n新的话题\n接下来介绍交通摄像头。'
    quotes = evidence_windows(SourcePassage(text, 0, len(text)))
    for quote in quotes:
        if '激活缓存需要付费' in quote.text:
            assert '摄像头' not in quote.text
