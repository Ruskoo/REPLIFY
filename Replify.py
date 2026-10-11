"""
Replify - An Interactive REPL for a Custom Language
CS 200 - Principles of Programming Languages

Features implemented in this version:
  1. Real-time Evaluation  - each line is lexed, parsed and evaluated as soon as it is entered
  2. Persistent Session State - variables stay available across inputs

Pipeline:  input -> Lexer -> Parser (AST) -> Interpreter -> output

Grammar (CFG) of the Replify language:
    statement  -> IDENTIFIER '=' expression
                | expression
    expression -> term (('+' | '-') term)*
    term       -> factor (('*' | '/') factor)*
    factor     -> NUMBER
                | IDENTIFIER
                | '(' expression ')'
                | '-' factor
"""


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ReplifyError(Exception):
    """Base class for all errors in Replify, so the REPL can catch them."""


class LexError(ReplifyError):
    pass


class ParseError(ReplifyError):
    pass


class EvalError(ReplifyError):
    pass


# ---------------------------------------------------------------------------
# 1. LEXER - turns raw text into tokens
# ---------------------------------------------------------------------------
# Token types
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


class Token:
    def __init__(self, kind, value=None):
        self.type = kind
        self.value = value



def lex(text):
    """Scan the input one character at a time and return a list of tokens."""
    tokens = []
    i = 0
    while i < len(text):
        ch = text[i]

        if ch.isspace():                      # skip whitespace
            i += 1

        elif ch.isdigit() or ch == ".":       # numbers like 5, 3.14
            start = i
            while i < len(text) and (text[i].isdigit() or text[i] == "."):
                i += 1
            number_text = text[start:i]
            if number_text.count(".") > 1:
                raise LexError(f"Invalid number '{number_text}'")
            tokens.append(Token(NUMBER, float(number_text)))

        elif ch.isalpha() or ch == "_":       # variable names like x, total_1
            start = i
            while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                i += 1
            tokens.append(Token(IDENT, text[start:i]))

        elif ch in SYMBOLS:                   # + - * / = ( )
            tokens.append(Token(SYMBOLS[ch], ch))
            i += 1

        else:
            raise LexError(f"Unexpected character '{ch}'")

    tokens.append(Token(EOF))
    return tokens


# ---------------------------------------------------------------------------
# 2. PARSER - turns tokens into an Abstract Syntax Tree (AST)
# ---------------------------------------------------------------------------
# AST nodes are plain tuples:
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
        """statement -> IDENTIFIER '=' expression | expression"""
        if (
            self.current().type == IDENT
            and self.tokens[self.pos + 1].type == EQUALS
        ):
            name = self.advance().value
            self.advance()  # skip '='
            value = self.expression()
            node = ("assign", name, value)
        else:
            node = self.expression()

        if self.current().type != EOF:
            raise ParseError(f"Unexpected '{self.current().value}'")
        return node

    def expression(self):
        """expression -> term (('+' | '-') term)*"""
        node = self.term()
        while self.current().type in (PLUS, MINUS):
            op = self.advance().value
            right = self.term()
            node = ("binop", op, node, right)
        return node

    def term(self):
        """term -> factor (('*' | '/') factor)*"""
        node = self.factor()
        while self.current().type in (STAR, SLASH):
            op = self.advance().value
            right = self.factor()
            node = ("binop", op, node, right)
        return node

    def factor(self):
        """factor -> NUMBER | IDENTIFIER | '(' expression ')' | '-' factor"""
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
# 3. INTERPRETER - walks the AST and computes the result
# ---------------------------------------------------------------------------
class Interpreter:
    def __init__(self):
        # Persistent Session State: this dictionary lives for the whole session,
        # so variables assigned on one line can be used on later lines.
        self.variables = {}

    def evaluate(self, node):
        kind = node[0]

        if kind == "num":
            return node[1]

        if kind == "var":
            name = node[1]
            if name not in self.variables:
                raise EvalError(f"Undefined variable '{name}'")
            return self.variables[name]

        if kind == "neg":
            return -self.evaluate(node[1])

        if kind == "assign":
            value = self.evaluate(node[2])
            self.variables[node[1]] = value
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
# 4. REPL LOOP - Read, Eval, Print, Loop
# ---------------------------------------------------------------------------
def format_result(value):
    """Show 8 instead of 8.0 when the number is a whole number."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def main():
    interpreter = Interpreter()

    print("Replify - Interactive REPL for a Custom Language")
    print("Type an expression or assignment. Type 'exit' to quit.\n")

    while True:                                    # L: Loop
        try:
            line = input("replify> ")              # R: Read
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        line = line.strip()
        if line == "":
            continue
        if line == "exit":
            print("Goodbye!")
            break

        try:
            tokens = lex(line)                     # lexical analysis
            tree = Parser(tokens).parse()          # parsing
            result = interpreter.evaluate(tree)    # E: Eval
            print(format_result(result))           # P: Print
        except ReplifyError as error:
            # Errors are reported but never crash the loop.
            print(f"Error: {error}")


if __name__ == "__main__":
    main()