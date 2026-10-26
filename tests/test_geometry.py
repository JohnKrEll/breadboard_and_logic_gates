import unittest

from breadboard.logic import GATES
from breadboard.ui.geometry import ROW_SLOTS, BoardGeometry
from breadboard.ui.symbols import outline


class Geometry(unittest.TestCase):
    def test_round_trip_and_fit(self):
        for columns, w, h in ((30, 800, 450), (30, 2600, 1500), (63, 1900, 1100), (30, 400, 900)):
            g = BoardGeometry(columns, w, h)
            self.assertLessEqual(g.left + g.board_width, w + 1e-9)
            self.assertLessEqual(g.top + g.board_height, h + 1e-9)
            for row in ROW_SLOTS:
                for column in range(1, columns + 1):
                    hole = f"{row}{column}"
                    self.assertEqual(g.hole_at(*g.hole_xy(hole)), hole)
            x, y = g.hole_xy("e5")
            self.assertIsNone(g.hole_at(x, y + g.pitch))            # the channel
            self.assertIsNone(g.hole_at(x + g.pitch * 0.45, y + g.pitch * 0.45))   # between holes

    def test_minimum_pitch_scrolls_instead(self):
        g = BoardGeometry(120, 600, 300, min_pitch=10)
        self.assertEqual(g.pitch, 10)
        self.assertGreater(g.board_width, 600)
        self.assertEqual(g.left, 0)

    def test_fonts_are_pixels(self):
        self.assertLess(BoardGeometry(30, 800, 450).font(), 0)


class Symbols(unittest.TestCase):
    def test_outlines_stay_inside_the_symbol(self):
        for name, gate in GATES.items():
            for style in ("ansi", "iec"):
                with self.subTest(gate=name, style=style):
                    h = 2 * gate.arity
                    o = outline(name, h, style)
                    for poly in o.polygons + o.lines:
                        for x, y in poly:
                            self.assertTrue(0 <= x <= 4 and -1e-9 <= y <= h + 1e-9, (x, y))
                    self.assertLessEqual(o.body_right, 4)
                    self.assertEqual(o.bubble is not None, name in ("NAND", "NOR", "NOT"))
                    if style == "iec":
                        self.assertTrue(o.label)


if __name__ == "__main__":
    unittest.main()
