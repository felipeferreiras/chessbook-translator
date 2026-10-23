"""Junção de linhas de um bloco, com tratamento do hífen no fim da linha.

Juntar linhas com um espaço simples quebra referências ("(9-" + "158)" vira
"9- 158") e palavras hifenizadas pela diagramação ("posi-" + "tion"). As
regras abaixo foram tiradas da contagem dos casos no livro de amostra:

| Fim da linha + início da seguinte | Exemplo | Resultado |
|---|---|---|
| dígito- + dígito | ``(9-`` / ``158)`` | ``(9-158)`` |
| casa- + palavra | ``d5-`` / ``pawn``; ``c2-`` / ``c3`` | ``d5-pawn``; ``c2-c3`` |
| x- + "and"/"or"/"to" (hífen suspenso) | ``g6-`` / ``and g4-squares`` | mantém o espaço |
| Nome- + Nome | ``Hansen-`` / ``Nimzovitch`` | ``Hansen-Nimzovitch`` |
| palavra- + minúscula, e a palavra inteira existe no livro | ``posi-`` / ``tion`` | ``position`` |
| palavra- + minúscula, palavra inteira desconhecida | ``queen-`` / ``and-rook`` | ``queen-and-rook`` |

O hífen só é removido com evidência do próprio documento; na dúvida, ele é
mantido e as linhas são unidas sem espaço.
"""

from __future__ import annotations

import re

_SUSPENDED = {"and", "or", "to", "nor"}
_WORD = re.compile(r"[A-Za-z]+")


def vocabulary(texts: list[str]) -> set[str]:
    """Palavras (minúsculas, 3+ letras) que aparecem inteiras no documento."""
    words: set[str] = set()
    for text in texts:
        for line in text.splitlines():
            parts = line.split()
            # A última palavra pode estar cortada pela hifenização: fica de fora.
            for token in parts[:-1] if line.rstrip().endswith("-") else parts:
                for w in _WORD.findall(token):
                    if len(w) >= 3:
                        words.add(w.lower())
    return words


def join(prev_line: str, next_line: str, vocab: set[str]) -> tuple[str, bool]:
    """Como unir ``prev_line`` a ``next_line``.

    Devolve (separador, remover_hífen_final). O chamador já tirou os espaços do
    fim da linha anterior e do início da seguinte.
    """
    if not prev_line.endswith("-") or len(prev_line) < 2 or not next_line:
        return " ", False
    before, first = prev_line[-2], next_line[0]
    next_word = next_line.split(maxsplit=1)[0]
    if next_word.rstrip(".,;:)").lower() in _SUSPENDED:
        return " ", False
    if before.isdigit() and (first.isdigit() or first.islower()):
        return "", False
    if before.isalpha() and first.isupper():
        return "", False
    if before.isalpha() and first.islower():
        head = re.search(r"[A-Za-z]+$", prev_line[:-1])
        tail = re.match(r"[a-z]+", next_line)
        if head and tail and (head.group() + tail.group()).lower() in vocab:
            return "", True
        return "", False
    return " ", False
