"""Tests for Maestro hierarchy CSV parsing."""

import pytest

from maestro_ai_agent.services.maestro.hierarchy_csv import (
    HierarchyParseError,
    parse_maestro_hierarchy_csv,
)


def test_parse_sample_maestro_row() -> None:
    csv_text = (
        '67,10,"resource-id=com.example:id/btn; bounds=[0,0][100,40]; enabled=true; '
        'class=android.widget.Button; package=com.example",65\n'
        '68,11,"resource-id=com.example:id/title; text=Hello; class=android.widget.TextView; '
        'package=com.example",67\n'
    )
    snapshot = parse_maestro_hierarchy_csv(csv_text)
    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[0].node_index == "67"
    assert snapshot.nodes[0].depth == 10
    assert snapshot.nodes[0].parent_index == "65"
    assert snapshot.nodes[0].resource_id == "com.example:id/btn"
    assert snapshot.nodes[0].class_name == "android.widget.Button"
    assert snapshot.nodes[0].enabled is True
    assert snapshot.nodes[1].text == "Hello"
    assert snapshot.nodes[1].visible_text == "Hello"


def test_parse_ios_five_column_bounds_and_accessibility_text() -> None:
    """Real iOS CSV shape: bounds column, then attributes with accessibilityText labels."""
    csv_text = """element_num,depth,bounds,attributes,parent_num
40,11,"[25,795][99,849]","accessibilityText=Home; enabled=true; selected=true",39
41,12,"[48,801][76,829]","resource-id=home; enabled=true",40
42,11,"[89,795][163,849]","accessibilityText=Cart; enabled=true",39
43,12,"[112,801][140,829]","resource-id=bag; enabled=true",42
"""
    snapshot = parse_maestro_hierarchy_csv(csv_text)
    assert any("header" in w.lower() for w in snapshot.parse_warnings)
    by_idx = {n.node_index: n for n in snapshot.nodes}
    assert by_idx["42"].visible_text == "Cart"
    assert by_idx["42"].text is None
    assert by_idx["42"].bounds == "[89,795][163,849]"
    assert by_idx["43"].resource_id == "bag"
    assert by_idx["43"].visible_text is None
    assert by_idx["40"].visible_text == "Home"


def test_parse_accepts_three_column_rows() -> None:
    csv_text = (
        '1,0,"resource-id=a:id; class=android.view.View; package=com.a"\n'
        '2,1,"text=Child; class=android.widget.TextView; package=com.a"\n'
    )
    snapshot = parse_maestro_hierarchy_csv(csv_text)
    assert len(snapshot.nodes) == 2
    assert snapshot.nodes[1].parent_index is None


def test_parse_skips_detected_header_row() -> None:
    csv_text = (
        "index,depth,attributes,parent\n"
        '10,0,"resource-id=a:id; class=android.view.View; package=com.a",\n'
    )
    snapshot = parse_maestro_hierarchy_csv(csv_text)
    assert len(snapshot.nodes) == 1
    assert any("header" in w.lower() for w in snapshot.parse_warnings)


def test_parse_single_column_attribute_blob() -> None:
    csv_text = "resource-id=demo:id/root; class=android.widget.FrameLayout; enabled=false"
    snapshot = parse_maestro_hierarchy_csv(csv_text)
    assert len(snapshot.nodes) == 1
    assert snapshot.nodes[0].node_index == "0"
    assert snapshot.nodes[0].enabled is False


def test_empty_csv_does_not_raise() -> None:
    snapshot = parse_maestro_hierarchy_csv("")
    assert snapshot.nodes == []
    assert snapshot.parse_warnings


def test_malformed_non_empty_raises() -> None:
    with pytest.raises(HierarchyParseError):
        parse_maestro_hierarchy_csv("this-is-not-a-valid-row-shape")


def test_invalid_depth_skips_row_and_raises_when_all_bad() -> None:
    with pytest.raises(HierarchyParseError):
        parse_maestro_hierarchy_csv('1,not-a-depth,"class=android.view.View",0')
