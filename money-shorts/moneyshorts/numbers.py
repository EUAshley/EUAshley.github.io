"""Number handling shared by the fact-checker, narration and visuals.

- `find_numbers` pulls every numeric claim out of a script line so it can be
  checked against the fact ledger.
- `speakable` rewrites digits into words so the TTS voice reads them
  naturally ("$297.2 billion" -> "two hundred ninety-seven point two billion dollars")
  while captions keep the compact digit form.
- `fmt_money` / `fmt_num` produce on-screen labels.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCALES = {
    "thousand": 1e3, "k": 1e3,
    "million": 1e6, "m": 1e6,
    "billion": 1e9, "b": 1e9,
    "trillion": 1e12, "t": 1e12,
}

NUM_RE = re.compile(
    r"(?P<cur>\$)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<pct>%|percent\b)|\s*(?P<scale>thousand|million|billion|trillion)\b|(?P<abbr>[KMBT])\b)?",
    re.IGNORECASE,
)


@dataclass
class NumberToken:
    text: str
    value: float
    is_money: bool
    is_percent: bool
    start: int
    end: int

    def candidates(self) -> list[float]:
        """Values this token may legitimately represent in the fact ledger."""
        vals = [self.value]
        if self.is_percent:
            vals.append(self.value / 100.0)
        return vals


def find_numbers(text: str) -> list[NumberToken]:
    out = []
    for m in NUM_RE.finditer(text):
        num = float(m.group("num").replace(",", ""))
        scale = (m.group("scale") or m.group("abbr") or "").lower()
        num *= SCALES.get(scale, 1)
        out.append(NumberToken(
            text=m.group(0).strip(),
            value=num,
            is_money=bool(m.group("cur")),
            is_percent=bool(m.group("pct")),
            start=m.start(),
            end=m.end(),
        ))
    return out


# ---------------------------------------------------------------- words

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
         "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_BIG = [(10**12, "trillion"), (10**9, "billion"), (10**6, "million"), (10**3, "thousand")]


def int_words(n: int) -> str:
    if n < 0:
        return "minus " + int_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _TENS[t] + ("-" + _ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _ONES[h] + " hundred" + (" " + int_words(r) if r else "")
    for size, name in _BIG:
        if n >= size:
            q, r = divmod(n, size)
            return int_words(q) + " " + name + (" " + int_words(r) if r else "")
    raise AssertionError


def year_words(n: int) -> str:
    if 2000 <= n <= 2009:
        return int_words(n)
    hi, lo = divmod(n, 100)
    if lo == 0:
        return int_words(hi) + " hundred"
    return int_words(hi) + " " + ("oh " + _ONES[lo] if lo < 10 else int_words(lo))


def decimal_words(s: str) -> str:
    whole, _, frac = s.partition(".")
    out = int_words(int(whole))
    if frac:
        out += " point " + " ".join(_ONES[int(d)] for d in frac)
    return out


def _speak_token(m: re.Match) -> str:
    raw = m.group("num").replace(",", "")
    cur = m.group("cur")
    pct = m.group("pct")
    scale = (m.group("scale") or "").lower()
    abbr = (m.group("abbr") or "").lower()
    if abbr:
        scale = {"k": "thousand", "m": "million", "b": "billion", "t": "trillion"}[abbr]

    if pct:
        return decimal_words(raw) + " percent"
    if cur and not scale and "." in raw:
        dollars, cents = raw.split(".")
        cents = int(cents.ljust(2, "0")[:2])
        d = int(dollars)
        if d == 0:
            return f"{int_words(cents)} cents"
        after_article = re.search(r"\b(the|a|an|this|that)\s+$", m.string[:m.start()], re.IGNORECASE)
        dword = ("one dollar" if after_article else "a dollar") if d == 1 else f"{int_words(d)} dollars"
        return dword + (f" {int_words(cents)}" if cents else "")
    if not cur and not scale and "." not in raw and len(raw) == 4 and 1700 <= int(raw) <= 2099:
        return year_words(int(raw))
    words = decimal_words(raw)
    if scale:
        words += " " + scale
    if cur:
        words += " dollar" if (raw == "1" and not scale) else " dollars"
    return words


def speakable(text: str) -> str:
    """Rewrite a script line so every number is spelled out for the TTS voice."""
    text = NUM_RE.sub(_speak_token, text)
    text = text.replace("&", " and ").replace("—", ", ").replace("–", " to ")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- labels

def fmt_money(v: float, digits: int | None = None, compact: bool = True) -> str:
    return "$" + fmt_num(v, digits, compact)


def fmt_num(v: float, digits: int | None = None, compact: bool = True) -> str:
    a = abs(v)
    if compact:
        for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
            if a >= size:
                d = 1 if digits is None else digits
                s = f"{v / size:,.{d}f}"
                if digits is None and s.endswith(".0"):
                    s = s[:-2]
                return s + suffix
    if digits is None:
        digits = 2 if (a < 100 and v != int(v)) else 0
    return f"{v:,.{digits}f}"


# ---------------------------------------------------------------- templates
# Visual text pulls numbers from the fact ledger with "{fact_id:fmt}" so that
# nothing on screen can drift from what was fact-checked.

TEMPLATE_RE = re.compile(r"\{(?P<id>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<fmt>[a-z0-9]+))?\}")


def format_value(v: float, fmt: str | None) -> str:
    fmt = fmt or "num"
    if fmt == "money":
        return fmt_money(v)
    if fmt.startswith("money") and fmt[5:].isdigit():
        return fmt_money(v, int(fmt[5:]))
    if fmt == "dollars":  # exact dollars and cents: $1.50
        return f"${v:,.2f}" if v != int(v) else f"${v:,.0f}"
    if fmt == "pct":
        return f"{v * 100:.0f}%"
    if fmt.startswith("pct") and fmt[3:].isdigit():
        return f"{v * 100:.{int(fmt[3:])}f}%"
    if fmt == "int":
        return f"{v:,.0f}"
    if fmt == "raw":
        return f"{v:g}" if v != int(v) else str(int(v))
    if fmt == "num":
        return fmt_num(v)
    if fmt.startswith("num") and fmt[3:].isdigit():
        return fmt_num(v, int(fmt[3:]))
    raise ValueError(f"unknown number format '{fmt}'")


def fill_template(s: str, values: dict[str, float]) -> str:
    return TEMPLATE_RE.sub(lambda m: format_value(values[m.group("id")], m.group("fmt")), s)


def template_refs(s: str) -> list[str]:
    return [m.group("id") for m in TEMPLATE_RE.finditer(s)]


def bare_digits(s: str) -> list[str]:
    """Numbers written directly in a string (outside {templates})."""
    return [t.text for t in find_numbers(TEMPLATE_RE.sub("", s))]
