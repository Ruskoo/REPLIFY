"""
Replify - An Interactive REPL for a Custom Language
CS 200 - Principles of Programming Languages

Pipeline (Chapter 3.2):
    input -> Lexer -> Parser (AST) -> Semantic Analyzer -> Interpreter -> output

Key features (from the proposal):
    1. Error handling          - lexical, syntax, semantic and runtime errors never crash the loop
    2. Real-time evaluation    - every line is evaluated as soon as it is entered
    3. Auto-completion         - Tab / as-you-type suggestions for variables and commands
    4. Syntax highlighting     - color-coded input and output
    5. Persistent session state - variables stay available in the symbol table
    6. Command history         - up/down arrows to recall and edit, 'history' to list, '!n' to re-run
    7. Exit and clear commands
    8. Save file and script loading

Auto-completion, highlighting and arrow-key history use the prompt_toolkit library:
    pip install prompt_toolkit
Without it, Replify still runs but in basic mode (no completion or live highlighting).

Grammar (CFG in EBNF, Chapter 3.5):
    Statement  -> Assignment | Expression
    Assignment -> IDENTIFIER EQUALS Expression
    Expression -> Term ((PLUS | MINUS) Term)*
    Term       -> Factor ((STAR | SLASH) Factor)*
    Factor     -> NUMBER
                | IDENTIFIER
                | LPAREN Expression RPAREN
                | MINUS Factor
"""

import os
import re
import sys

# ---------------------------------------------------------------------------
# Optional library: prompt_toolkit (auto-completion, highlighting, history keys)
# ---------------------------------------------------------------------------
try:
    from prompt_toolkit import PromptSession, print_formatted_text
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.lexers import Lexer

    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

# The fancy prompt is only used in a real terminal (not when input is piped in).
USE_PROMPT_TOOLKIT = HAS_PROMPT_TOOLKIT and sys.stdin.isatty() and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Colors (ANSI) used for color-coded output
# ---------------------------------------------------------------------------
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
GRAY = "\033[90m"

if os.name == "nt":
    os.system("")          # turns on ANSI color support in the Windows console


def paint(text, color):
    return f"{color}{text}{RESET}"


def show(text):
    """Print text that may contain ANSI colors."""
    if USE_PROMPT_TOOLKIT:
        print_formatted_text(ANSI(text))
    else:
        print(text)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ReplifyError(Exception):
    """Parent of all Replify errors, so the REPL can catch them in one place."""


class LexError(ReplifyError):
    pass


class ParseError(ReplifyError):
    pass


class SemanticError(ReplifyError):
    pass


class EvalError(ReplifyError):
    pass


# ---------------------------------------------------------------------------
# Commands (also the reserved words that cannot be used as variable names)
# ---------------------------------------------------------------------------
COMMANDS = ("exit", "clear", "debug", "history", "save", "load")


def is_command(line):
    """A line is a command if it starts with a command word.
    'exit = 5' is not a command; it is an attempt to use a reserved name,
    so it goes through the pipeline and the semantic analyzer rejects it."""
    parts = line.split()
    if not parts or parts[0] not in COMMANDS:
        return False
    return len(parts) == 1 or parts[1] != "="


# ---------------------------------------------------------------------------
# 1. LEXER - turns raw text into tokens
# ---------------------------------------------------------------------------
NUMBER = "NUMBER"
IDENT = "IDENTIFIER"
PLUS = "PLUS"
MINUS = "MINUS"
STAR = "STAR"
SLASH = "SLASH"
EQUALS = "EQUALS"
LPAREN = "LPAREN"
RPAREN = "RPAREN"
EOF = "EOF"

SYMBOLS = {
    "+": PLUS,
    "-": MINUS,
    "*": STAR,
    "/": SLASH,
    "=": EQUALS,
    "(": LPAREN,
    ")": RPAREN,
}

# Number pattern from Chapter 3.4:  [0-9]+(\.[0-9]+)?
NUMBER_PATTERN = re.compile(r"[0-9]+(\.[0-9]+)?")


class Token:
    def __init__(self, token_type, value=None):
        self.type = token_type
        self.value = value


def lex(text):
    """Scan the input left to right, one character at a time, and return tokens."""
    tokens = []
    i = 0
    while i < len(text):
        ch = text[i]

        if ch.isspace():                       # skip spaces and tabs
            i += 1

        elif ch == "#":                        # comment: ignore the rest of the line
            break

        elif ch.isdigit() or ch == ".":        # numbers: 5, 26, 3.5
            start = i
            while i < len(text) and (text[i].isdigit() or text[i] == "."):
                i += 1
            number_text = text[start:i]
            if not NUMBER_PATTERN.fullmatch(number_text):
                raise LexError(f"Invalid number '{number_text}'")
            if "." in number_text:
                tokens.append(Token(NUMBER, float(number_text)))
            else:
                tokens.append(Token(NUMBER, int(number_text)))

        elif ch.isalpha() or ch == "_":        # identifiers: x, Student_1
            start = i
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(Token(IDENT, text[start:i]))

        elif ch in SYMBOLS:                    # + - * / = ( )
            tokens.append(Token(SYMBOLS[ch], ch))
            i += 1

        else:
            raise LexError(f"Unexpected character '{ch}'")

    tokens.append(Token(EOF))
    return tokens


# ---------------------------------------------------------------------------
# 2. PARSER - turns tokens into an Abstract Syntax Tree (AST)
# ---------------------------------------------------------------------------
# AST nodes are tuples:
#   ("num", value)
#   ("var", name)
#   ("neg", node)
#   ("binop", operator, left, right)
#   ("assign", name, node)
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        return self.tokens[self.pos]

    def advance(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self):
        """Statement -> Assignment | Expression"""
        if self.current().type == IDENT and self.tokens[self.pos + 1].type == EQUALS:
            name = self.advance().value
            self.advance()                     # skip '='
            value = self.expression()
            node = ("assign", name, value)
        else:
            node = self.expression()

        if self.current().type != EOF:
            raise ParseError(f"Unexpected '{self.current().value}'")
        return node

    def expression(self):
        """Expression -> Term ((PLUS | MINUS) Term)*"""
        node = self.term()
        while self.current().type in (PLUS, MINUS):
            op = self.advance().value
            right = self.term()
            node = ("binop", op, node, right)
        return node

    def term(self):
        """Term -> Factor ((STAR | SLASH) Factor)*"""
        node = self.factor()
        while self.current().type in (STAR, SLASH):
            op = self.advance().value
            right = self.factor()
            node = ("binop", op, node, right)
        return node

    def factor(self):
        """Factor -> NUMBER | IDENTIFIER | LPAREN Expression RPAREN | MINUS Factor"""
        token = self.current()

        if token.type == NUMBER:
            self.advance()
            return ("num", token.value)

        if token.type == IDENT:
            self.advance()
            return ("var", token.value)

        if token.type == MINUS:
            self.advance()
            return ("neg", self.factor())

        if token.type == LPAREN:
            self.advance()
            node = self.expression()
            if self.current().type != RPAREN:
                raise ParseError("Missing closing parenthesis ')'")
            self.advance()
            return node

        if token.type == EOF:
            raise ParseError("Unexpected end of input")
        raise ParseError(f"Unexpected '{token.value}'")


# ---------------------------------------------------------------------------
# Symbol Table (Chapter 3.8) - stores variable names and their values
# ---------------------------------------------------------------------------
def type_name(value):
    """Return 'int' or 'float' for a stored value."""
    if isinstance(value, int):
        return "int"
    return "float"


class SymbolTable:
    def __init__(self):
        # Persistent session state: lives for the whole session.
        self.table = {}

    def define(self, name, value):
        self.table[name] = value

    def contains(self, name):
        return name in self.table

    def lookup(self, name):
        return self.table[name]

    def type_of(self, name):
        return type_name(self.table[name])

    def names(self):
        return sorted(self.table)


# ---------------------------------------------------------------------------
# 3. SEMANTIC ANALYZER - checks the AST before it is executed
# ---------------------------------------------------------------------------
class SemanticAnalyzer:
    def __init__(self, symbols):
        self.symbols = symbols

    def check(self, node):
        """Check a node and return its type ('int' or 'float')."""
        kind = node[0]

        if kind == "num":
            return type_name(node[1])

        if kind == "var":
            name = node[1]
            if not self.symbols.contains(name):
                raise SemanticError(f"Undefined variable '{name}'")
            return self.symbols.type_of(name)

        if kind == "neg":
            return self.require_numeric(self.check(node[1]))

        if kind == "assign":
            name = node[1]
            if name in COMMANDS:
                raise SemanticError(
                    f"'{name}' is a reserved command and cannot be used as a variable name"
                )
            return self.check(node[2])

        if kind == "binop":
            _, op, left, right = node
            left_type = self.require_numeric(self.check(left))
            right_type = self.require_numeric(self.check(right))
            # Division always gives a float. Otherwise float wins if either side is float.
            if op == "/" or "float" in (left_type, right_type):
                return "float"
            return "int"

        raise SemanticError("Unknown expression")

    def require_numeric(self, value_type):
        """Arithmetic needs int or float operands."""
        if value_type not in ("int", "float"):
            raise SemanticError("Arithmetic requires numeric operands")
        return value_type


# ---------------------------------------------------------------------------
# 4. INTERPRETER - walks the AST and computes the result
# ---------------------------------------------------------------------------
class Interpreter:
    def __init__(self, symbols):
        self.symbols = symbols

    def evaluate(self, node):
        kind = node[0]

        if kind == "num":
            return node[1]

        if kind == "var":
            return self.symbols.lookup(node[1])

        if kind == "neg":
            return -self.evaluate(node[1])

        if kind == "assign":
            value = self.evaluate(node[2])
            self.symbols.define(node[1], value)     # only stored after success
            return value

        if kind == "binop":
            _, op, left, right = node
            a = self.evaluate(left)
            b = self.evaluate(right)
            if op == "+":
                return a + b
            if op == "-":
                return a - b
            if op == "*":
                return a * b
            if op == "/":
                if b == 0:
                    raise EvalError("Division by zero")
                return a / b

        raise EvalError("Unknown expression")


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def format_result(value):
    """Show ints as they are, and trim floating point noise (0.1 + 0.2)."""
    if isinstance(value, float):
        return str(round(value, 10))
    return str(value)


def token_text(token):
    """Readable token, e.g. IDENTIFIER(x) or NUMBER(5) or PLUS."""
    if token.type in (NUMBER, IDENT):
        return f"{token.type}({token.value})"
    return token.type


def tree_lines(node, depth=1):
    """Return the AST as indented text lines (used in debug mode)."""
    pad = "  " * depth
    kind = node[0]
    if kind == "num":
        return [f"{pad}NUM {node[1]}"]
    if kind == "var":
        return [f"{pad}VAR {node[1]}"]
    if kind == "neg":
        return [f"{pad}NEG"] + tree_lines(node[1], depth + 1)
    if kind == "assign":
        return [f"{pad}ASSIGN {node[1]}"] + tree_lines(node[2], depth + 1)
    return (
        [f"{pad}BINOP {node[1]}"]
        + tree_lines(node[2], depth + 1)
        + tree_lines(node[3], depth + 1)
    )


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def add_extension(filename):
    """Scripts use the .rpl extension unless another one is given."""
    if "." not in os.path.basename(filename):
        return filename + ".rpl"
    return filename


# ---------------------------------------------------------------------------
# The Replify session: ties the whole pipeline together
# ---------------------------------------------------------------------------
class Replify:
    def __init__(self):
        self.symbols = SymbolTable()
        self.analyzer = SemanticAnalyzer(self.symbols)
        self.interpreter = Interpreter(self.symbols)
        self.debug = False
        self.history = []          # every line entered (for 'history' and '!n')
        self.script_lines = []     # statements that ran successfully (used by 'save')

    def run(self, line):
        """Run one statement through the whole pipeline.
        Returns the result, or None for a blank line or a comment-only line."""
        tokens = lex(line)                                   # lexical analysis
        if len(tokens) == 1:
            return None
        if self.debug:
            show(paint("Tokens: " + "  ".join(token_text(t) for t in tokens), GRAY))

        tree = Parser(tokens).parse()                        # syntax analysis
        if self.debug:
            show(paint("Tree:", GRAY))
            for text in tree_lines(tree):
                show(paint(text, GRAY))

        result_type = self.analyzer.check(tree)              # semantic analysis
        result = self.interpreter.evaluate(tree)             # evaluation
        if self.debug:
            show(paint(f"Type: {result_type}", GRAY))

        self.script_lines.append(line)
        return result

    # ----- commands -----
    def handle_command(self, line):
        """Run a command. Returns False when the REPL should stop."""
        parts = line.split(None, 1)
        command = parts[0]
        argument = parts[1].strip() if len(parts) > 1 else ""

        if command == "exit":
            show(paint("Goodbye!", CYAN))
            return False

        if command == "clear":
            clear_screen()

        elif command == "debug":
            self.debug = not self.debug
            show(paint("Debug mode is ON" if self.debug else "Debug mode is OFF", CYAN))

        elif command == "history":
            self.show_history()

        elif command == "save":
            show(paint(self.save_script(argument), CYAN))

        elif command == "load":
            self.load_script(argument)

        return True

    def show_history(self):
        if not self.history:
            show(paint("History is empty", GRAY))
        for number, entry in enumerate(self.history, start=1):
            show(paint(f"{number:>3}  ", GRAY) + entry)

    def save_script(self, filename):
        if filename == "":
            raise EvalError("Usage: save <filename>")
        filename = add_extension(filename)
        try:
            with open(filename, "w", encoding="utf-8") as file:
                for line in self.script_lines:
                    file.write(line + "\n")
        except OSError:
            raise EvalError(f"Could not save file '{filename}'")
        return f"Saved {len(self.script_lines)} line(s) to {filename}"

    def load_script(self, filename):
        if filename == "":
            raise EvalError("Usage: load <filename>")
        filename = add_extension(filename)
        try:
            with open(filename, "r", encoding="utf-8") as file:
                lines = file.read().splitlines()
        except FileNotFoundError:
            raise EvalError(f"File '{filename}' not found")
        except OSError:
            raise EvalError(f"Could not read file '{filename}'")

        # Run the script line by line. It stops at the first error.
        for number, raw in enumerate(lines, start=1):
            line = raw.strip()
            if line == "":
                continue
            if is_command(line):
                raise EvalError(f"Line {number}: commands cannot be used inside a script")
            try:
                result = self.run(line)
            except ReplifyError as error:
                raise EvalError(f"Line {number}: {error}")
            if result is not None:
                show(paint(f"  [{number}] ", GRAY) + line + paint("  =>  ", GRAY)
                     + paint(format_result(result), GREEN))
        show(paint(f"Loaded {filename}", CYAN))


# ---------------------------------------------------------------------------
# Auto-completion and syntax highlighting (need prompt_toolkit)
# ---------------------------------------------------------------------------
if HAS_PROMPT_TOOLKIT:

    # One piece of the input at a time: comment, number, identifier, operator, space, bad character
    HIGHLIGHT_PATTERN = re.compile(
        r"(?P<comment>#.*)"
        r"|(?P<number>[0-9]+(?:\.[0-9]+)?)"
        r"|(?P<ident>[A-Za-z_][A-Za-z0-9_]*)"
        r"|(?P<op>[+\-*/=()])"
        r"|(?P<space>\s+)"
        r"|(?P<bad>.)"
    )

    class ReplifyCompleter(Completer):
        """Suggests variable names and commands as the user types."""

        def __init__(self, symbols):
            self.symbols = symbols

        def get_completions(self, document, complete_event):
            word = document.get_word_before_cursor()
            if word == "":
                return
            at_start = document.text_before_cursor.lstrip() == word

            if at_start:
                for command in COMMANDS:
                    if command.startswith(word) and command != word:
                        yield Completion(command, start_position=-len(word),
                                         display_meta="command")
            for name in self.symbols.names():
                if name.startswith(word) and name != word:
                    yield Completion(name, start_position=-len(word),
                                     display_meta=self.symbols.type_of(name) + " variable")

    class ReplifyHighlighter(Lexer):
        """Colors the input while the user types."""

        def __init__(self, symbols):
            self.symbols = symbols

        def lex_document(self, document):
            lines = document.lines

            def get_line(line_number):
                return self.highlight(lines[line_number])

            return get_line

        def highlight(self, line):
            stripped = line.strip()

            if stripped.startswith("!"):                    # !n re-run
                return [("ansiyellow", line)]

            if stripped and is_command(stripped):           # exit, clear, save file ...
                word = stripped.split()[0]
                start = line.index(word)
                return [("", line[:start]),
                        ("ansimagenta bold", word),
                        ("", line[start + len(word):])]

            fragments = []
            for match in HIGHLIGHT_PATTERN.finditer(line):
                text = match.group(0)
                group = match.lastgroup
                if group == "comment":
                    style = "ansibrightblack"
                elif group == "number":
                    style = "ansicyan"
                elif group == "ident":
                    style = "ansigreen" if self.symbols.contains(text) else ""
                elif group == "op":
                    style = "ansiyellow"
                elif group == "bad":
                    style = "bg:ansired ansiwhite"
                else:
                    style = ""
                fragments.append((style, text))
            return fragments


def build_session(app):
    """Create the prompt with history, auto-completion and syntax highlighting."""
    return PromptSession(
        history=InMemoryHistory(),
        completer=ReplifyCompleter(app.symbols),
        lexer=ReplifyHighlighter(app.symbols),
        complete_while_typing=True,
    )


def read_line(session):
    if session is not None:
        return session.prompt(ANSI(paint("replify> ", CYAN)))
    return input("replify> ")


# ---------------------------------------------------------------------------
# REPL LOOP - Read, Eval, Print, Loop
# ---------------------------------------------------------------------------
def main():
    app = Replify()
    session = build_session(app) if USE_PROMPT_TOOLKIT else None

    show(paint("Replify - Interactive REPL for a Custom Language", CYAN))
    print("Type an expression or assignment, for example:  x = 5 + 3")
    print("Commands: exit, clear, debug, history, save <file>, load <file>, !<n> re-runs history entry n")
    if not HAS_PROMPT_TOOLKIT:
        show(paint("Tip: run 'pip install prompt_toolkit' to turn on auto-completion, "
                   "highlighting and arrow-key history.", GRAY))
    print()

    while True:                                              # L: Loop
        try:
            line = read_line(session)                        # R: Read
        except (EOFError, KeyboardInterrupt):
            show(paint("\nGoodbye!", CYAN))
            break

        line = line.strip()
        if line == "":
            continue

        # !n re-runs entry n from the history
        match = re.fullmatch(r"!(\d+)", line)
        if match:
            number = int(match.group(1))
            if number < 1 or number > len(app.history):
                show(paint(f"Error: No history entry {number}", RED))
                continue
            line = app.history[number - 1]
            show(paint(f"  {line}", GRAY))

        command_line = is_command(line)
        if not (command_line and line.split()[0] == "history"):
            app.history.append(line)

        try:
            if command_line:
                if not app.handle_command(line):
                    break
                continue
            result = app.run(line)                           # E: Eval
            if result is not None:
                show(paint(format_result(result), GREEN))    # P: Print
        except ReplifyError as error:
            # Errors are reported but never crash the loop.
            show(paint(f"Error: {error}", RED))


if __name__ == "__main__":
    main()