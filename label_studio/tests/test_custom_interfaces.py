from pathlib import Path

from django.test import SimpleTestCase

from core.label_config import get_all_control_tag_tuples, validate_label_config


class ReactCodeConfigTests(SimpleTestCase):
    def test_reactcode_preserves_native_output_schema(self):
        config = (
            Path(__file__).resolve().parents[2]
            / 'web/libs/editor/src/custom/examples/document-assessment.xml'
        ).read_text(encoding='utf-8')
        validate_label_config(config)
        self.assertEqual(
            set(get_all_control_tag_tuples(config)),
            {'quality|document|choices', 'score|document|number', 'comment|document|textarea'},
        )
