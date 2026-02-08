import unittest

from app import build_csv_data, csv_text


class CsvExportTests(unittest.TestCase):
    def test_csv_text_wraps_value_for_excel(self):
        self.assertEqual(csv_text(None), "")
        self.assertEqual(csv_text(10), '="10"')
        self.assertEqual(csv_text("020"), '="020"')

    def test_build_csv_data_includes_bom_and_delimiters(self):
        headers = ["DATA", "N.º Sumário"]
        rows = [["01/01/2024", csv_text(10)], ["02/01/2024", csv_text("020")]]
        data = build_csv_data(headers, rows)
        self.assertTrue(data.startswith("\ufeff"))
        self.assertIn("DATA;N.º Sumário", data)
        self.assertIn('01/01/2024;"=""10"""', data)
        self.assertIn('02/01/2024;"=""020"""', data)


if __name__ == "__main__":
    unittest.main()
