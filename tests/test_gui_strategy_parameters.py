from __future__ import annotations

import os
import unittest


class GuiStrategyParameterTests(unittest.TestCase):
    def test_dynamic_parameter_widgets_keep_chinese_labels_and_english_values(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt6.QtWidgets import QApplication, QDialogButtonBox

        from optionsentry.gui.app import StrategyEditDialog
        from optionsentry.strategy_base import (
            Strategy,
            StrategyCompilation,
            StrategyParameterSpec,
        )
        from optionsentry.strategy_registry import STRATEGY_REGISTRY, register_strategy

        @register_strategy("gui_parameter_test")
        class GuiParameterStrategy(Strategy):
            display_name = "动态参数测试"
            parameter_specs = (
                StrategyParameterSpec(
                    "direction",
                    "方向",
                    "enum",
                    default="both",
                    choices=("both", "call", "put"),
                    choice_labels=("双向", "认购", "认沽"),
                ),
                StrategyParameterSpec(
                    "window",
                    "窗口",
                    "int",
                    default=20,
                    minimum=1,
                    maximum=100,
                ),
                StrategyParameterSpec("enabled_flag", "附加开关", "bool", default=True),
                StrategyParameterSpec("note", "备注", "string", default="demo"),
                StrategyParameterSpec("ratio", "比例", "float", default=0.05),
            )

            def compile(self, universe):
                return StrategyCompilation(
                    strategy_id=self.id,
                    strategy_type=self.type_name,
                    name=self.name,
                    units=(),
                )

        try:
            app = QApplication.instance() or QApplication([])
            dialog = StrategyEditDialog(
                strategy_type="gui_parameter_test",
                strategy_id="gui_parameter_test",
                name="动态参数测试",
                parameters=GuiParameterStrategy.default_parameters(),
            )

            direction = dialog.parameter_widgets["direction"]
            self.assertEqual(
                [direction.itemText(index) for index in range(direction.count())],
                ["双向", "认购", "认沽"],
            )
            self.assertEqual(
                [direction.itemData(index) for index in range(direction.count())],
                ["both", "call", "put"],
            )
            direction.setCurrentIndex(2)
            dialog.parameter_widgets["window"].setValue(30)
            dialog.parameter_widgets["enabled_flag"].setChecked(False)
            dialog.parameter_widgets["note"].setText("自定义")
            dialog.parameter_widgets["ratio"].setText("0.08")

            self.assertEqual(
                dialog.parameters(),
                {
                    "direction": "put",
                    "window": 30,
                    "enabled_flag": False,
                    "note": "自定义",
                    "ratio": 0.08,
                },
            )

            buttons = dialog.findChild(QDialogButtonBox)
            self.assertEqual(
                buttons.button(QDialogButtonBox.StandardButton.Ok).text(),
                "确定",
            )
            self.assertEqual(
                buttons.button(QDialogButtonBox.StandardButton.Cancel).text(),
                "取消",
            )
            app.processEvents()
            dialog.close()
        finally:
            STRATEGY_REGISTRY.pop("gui_parameter_test", None)


if __name__ == "__main__":
    unittest.main()
