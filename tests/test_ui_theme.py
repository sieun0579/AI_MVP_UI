from pathlib import Path


def test_figma_desktop_theme_is_present():
    source = Path("app.py").read_text()
    assert "--moment-rose: #bd6271" in source
    assert "data-testid=\"stSidebar\"" in source
    assert "border-radius: 3px 18px 18px" in source
    assert 'button[kind="secondary"]' in source


def test_chat_layout_follows_figma_message_order_and_alignment():
    source = Path("app.py").read_text()
    exchange = source.split("def render_exchange", 1)[1].split("for index, exchange", 1)[0]
    assert 'st.markdown(exchange["answer"]["answer"])' in exchange
    assert exchange.index('st.markdown(exchange["answer"]["answer"])') < exchange.index('##### 관련 문서·근거')
    assert ':has([data-testid="stChatMessageAvatarUser"])' in source
    assert 'class="brand-mark"' in source
    assert '[class*="st-key-menu-"] button' in source
    assert 'st.markdown(answer["answer"])\n        if documents:' in source
    assert "width: 100%; max-width: none;" in source
    assert "margin: 0 0 0 auto" in source
    assert '[data-testid="stExpander"] summary { background: var(--moment-soft-rose);' in source
    assert "accent-color: var(--moment-rose)" in source
