from agent_platform.engine.expr import evaluate, render


def test_render_template():
    assert render("hello {{ name }}", {"name": "world"}) == "hello world"


def test_condition_expression_native_result():
    assert evaluate("score > 5", {"score": 10}) is True
    assert evaluate("score > 5", {"score": 1}) is False


def test_expression_error_on_missing_variable():
    import pytest

    from agent_platform.engine.expr import ExpressionError

    with pytest.raises(ExpressionError):
        render("{{ missing }}", {})
