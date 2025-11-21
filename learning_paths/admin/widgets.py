"""
Shared widgets and utilities for admin.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from ..compat import get_course_keys_with_outlines


def get_course_keys_choices():
    """Get course keys in an adequate format for a choice field."""
    yield None, ""
    for key in get_course_keys_with_outlines():
        yield key, key


class CourseKeyDatalistWidget(forms.TextInput):
    """A widget that provides a datalist for course keys."""

    def __init__(self, choices=None, attrs=None):
        """Initialize the widget with a datalist and apply styles."""
        attrs = attrs or {}
        attrs.update(
            {
                "style": "width: 30em;",
                "class": "form-control datalist-input",
                "placeholder": _("Type to search courses..."),
            }
        )
        super().__init__(attrs)
        self.choices = choices or []

    def render(self, name, value, attrs=None, renderer=None):
        """Render the widget with a datalist."""
        final_attrs = attrs or {}
        data_list_id = f"datalist_{name}"
        final_attrs["list"] = data_list_id

        text_input_html = super().render(name, value, attrs, renderer)
        data_list_id = f"datalist_{name}"
        options = "\n".join(f'<option value="{choice}" />' for choice in self.choices)
        datalist_html = f'<datalist id="{data_list_id}">\n{options}\n</datalist>'
        return f"{text_input_html}\n{datalist_html}"
