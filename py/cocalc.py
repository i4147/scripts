from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Static


class CalculatorDisplay(Static):
    def render(self) -> str:
        return self.app.calculator.get_display()


class Calculator(App):
    BINDINGS = [("d", "clear_display", "Clear")]
    CSS = "\n    Screen {\n        align: center middle;\n    }\n        width: 40;\n        height: auto;\n        border: solid $accent;\n        background: $panel;\n        padding: 1;\n    }\n        width: 100%;\n        height: 3;\n        content-align: right middle;\n        background: $boost;\n        border: solid $primary;\n        text-style: bold;\n        margin-bottom: 1;\n    }\n    .button-row {\n        width: 100%;\n        height: auto;\n    }\n    Button {\n        width: 1fr;\n        height: 3;\n    }\n    .operator {\n        background: $accent 80%;\n    }\n    .equals {\n        background: $success 80%;\n    }\n    .clear {\n        background: $error 80%;\n    }\n    "

    def __init__(self) -> None:
        super().__init__()
        self.calculator = CalcEngine()

    def compose(self) -> ComposeResult:
        with Container(id="calculator-container"):
            yield CalculatorDisplay(id="display")
            with Vertical():
                with Horizontal(classes="button-row"):
                    yield Button("C", id="btn-clear", classes="clear")
                    yield Button("←", id="btn-backspace")
                    yield Button("÷", id="btn-divide", classes="operator")
                    yield Button("×", id="btn-multiply", classes="operator")
                with Horizontal(classes="button-row"):
                    yield Button("7", id="btn-7")
                    yield Button("8", id="btn-8")
                    yield Button("9", id="btn-9")
                    yield Button("−", id="btn-subtract", classes="operator")
                with Horizontal(classes="button-row"):
                    yield Button("4", id="btn-4")
                    yield Button("5", id="btn-5")
                    yield Button("6", id="btn-6")
                    yield Button("+", id="btn-add", classes="operator")
                with Horizontal(classes="button-row"):
                    yield Button("1", id="btn-1")
                    yield Button("2", id="btn-2")
                    yield Button("3", id="btn-3")
                    yield Button("=", id="btn-equals", classes="equals")
                with Horizontal(classes="button-row"):
                    yield Button("0", id="btn-0")
                    yield Button(".", id="btn-decimal")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-clear":
            self.calculator.clear()
        elif button_id == "btn-backspace":
            self.calculator.backspace()
        elif button_id == "btn-equals":
            self.calculator.calculate()
        elif button_id == "btn-add":
            self.calculator.set_operator("+")
        elif button_id == "btn-subtract":
            self.calculator.set_operator("-")
        elif button_id == "btn-multiply":
            self.calculator.set_operator("*")
        elif button_id == "btn-divide":
            self.calculator.set_operator("/")
        elif button_id == "btn-decimal":
            self.calculator.add_decimal()
        else:
            self.calculator.add_digit(digit)
        self.query_one(CalculatorDisplay).update()

    def action_clear_display(self) -> None:
        self.calculator.clear()
        self.query_one(CalculatorDisplay).update()


class CalcEngine:
    def __init__(self) -> None:
        self.display = "0"
        self.first_operand = None
        self.operator = None
        self.waiting_for_operand = False

    def add_digit(self, digit: str) -> None:
        if self.waiting_for_operand:
            self.display = digit
            self.waiting_for_operand = False
        elif self.display == "0":
            self.display = digit
        else:
            self.display += digit

    def add_decimal(self) -> None:
        if self.waiting_for_operand:
            self.display = "0."
            self.waiting_for_operand = False
        elif "." not in self.display:
            self.display += "."

    def set_operator(self, op: str) -> None:
        try:
            operand = float(self.display)
        except ValueError:
            return
        if self.first_operand is None:
            self.first_operand = operand
        elif self.operator:
            result = self._perform_calculation(self.first_operand, self.operator, operand)
            self.display = str(result)
            self.first_operand = result
        self.operator = op
        self.waiting_for_operand = True

    def calculate(self) -> None:
        try:
            operand = float(self.display)
        except ValueError:
            return
        if self.first_operand is not None and self.operator:
            result = self._perform_calculation(self.first_operand, self.operator, operand)
            self.display = str(result)
            self.first_operand = None
            self.operator = None
            self.waiting_for_operand = True

    def _perform_calculation(self, first: float, op: str, second: float) -> float:
        if op == "+":
            return first + second
        elif op == "-":
            return first - second
        elif op == "*":
            return first * second
        elif op == "/":
            if second == 0:
                return float("inf")
            return first / second
        return 0

    def backspace(self) -> None:
        if len(self.display) > 1:
            self.display = self.display[:-1]
        else:
            self.display = "0"

    def clear(self) -> None:
        self.display = "0"
        self.first_operand = None
        self.operator = None
        self.waiting_for_operand = False

    def get_display(self) -> str:
        return self.display


if __name__ == "__main__":
    app = Calculator()
    app.run()
