from __future__ import annotations

import re
from dataclasses import dataclass

from .nodes import Binary, Call, Identifier, Node, Number, String, Unary


class ParseError(ValueError):
    pass


TOKEN_RE = re.compile(
    r"""
    (?P<SPACE>\s+)
  | (?P<NUMBER>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<STRING>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<OP>>=|<=|==|!=|[+\-*/><=(),])
  | (?P<MISMATCH>.)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    position: int


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    for match in TOKEN_RE.finditer(text):
        kind = match.lastgroup or "MISMATCH"
        value = match.group()
        if kind == "SPACE":
            continue
        if kind == "MISMATCH":
            raise ParseError(f"Ký tự không hợp lệ {value!r} tại vị trí {match.start()}")
        tokens.append(Token(kind, value, match.start()))
    tokens.append(Token("EOF", "", len(text)))
    return tokens


PRECEDENCE = {
    "==": 10,
    "!=": 10,
    ">": 10,
    ">=": 10,
    "<": 10,
    "<=": 10,
    "+": 20,
    "-": 20,
    "*": 30,
    "/": 30,
}


class Parser:
    def __init__(self, text: str):
        self.text = text
        self.tokens = tokenize(text)
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.current
        self.index += 1
        return token

    def accept(self, value: str) -> bool:
        if self.current.value == value:
            self.advance()
            return True
        return False

    def expect(self, value: str) -> Token:
        if self.current.value != value:
            raise ParseError(
                f"Cần {value!r} tại vị trí {self.current.position}, gặp {self.current.value!r}"
            )
        return self.advance()

    def parse(self) -> Node:
        if not self.text.strip():
            raise ParseError("Biểu thức rỗng")
        node = self.parse_expression(0)
        if self.current.kind != "EOF":
            raise ParseError(
                f"Dữ liệu thừa {self.current.value!r} tại vị trí {self.current.position}"
            )
        return node

    def parse_expression(self, minimum_precedence: int) -> Node:
        left = self.parse_prefix()
        while self.current.value in PRECEDENCE:
            operator = self.current.value
            precedence = PRECEDENCE[operator]
            if precedence < minimum_precedence:
                break
            self.advance()
            right = self.parse_expression(precedence + 1)
            left = Binary(operator, left, right)
        return left

    def parse_prefix(self) -> Node:
        token = self.current
        if token.value in {"+", "-"}:
            self.advance()
            return Unary(token.value, self.parse_expression(40))
        if token.value == "(":
            self.advance()
            value = self.parse_expression(0)
            self.expect(")")
            return value
        if token.kind == "NUMBER":
            self.advance()
            return Number(token.value)
        if token.kind == "STRING":
            self.advance()
            value = bytes(token.value[1:-1], "utf-8").decode("unicode_escape")
            return String(value)
        if token.kind == "IDENT":
            self.advance()
            if self.accept("("):
                return self.parse_call(token.value)
            return Identifier(token.value)
        raise ParseError(f"Không thể đọc {token.value!r} tại vị trí {token.position}")

    def parse_call(self, name: str) -> Call:
        args: list[Node] = []
        kwargs: list[tuple[str, Node]] = []
        if self.accept(")"):
            return Call(name, tuple(args), tuple(kwargs))
        while True:
            if (
                self.current.kind == "IDENT"
                and self.tokens[self.index + 1].value == "="
            ):
                key = self.advance().value
                self.expect("=")
                kwargs.append((key, self.parse_expression(0)))
            else:
                if kwargs:
                    raise ParseError("Tham số vị trí không được đứng sau tham số có tên")
                args.append(self.parse_expression(0))
            if self.accept(")"):
                break
            self.expect(",")
        return Call(name, tuple(args), tuple(kwargs))


def parse(text: str) -> Node:
    return Parser(text).parse()
