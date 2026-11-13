from ranobe.ui.layout.breakpoints import Layout, layout_for


def test_layout_for_width():
    assert layout_for(360) is Layout.COMPACT
    assert layout_for(599) is Layout.COMPACT
    assert layout_for(600) is Layout.MEDIUM
    assert layout_for(800) is Layout.MEDIUM
    assert layout_for(1024) is Layout.EXPANDED
    assert layout_for(None) is Layout.EXPANDED
