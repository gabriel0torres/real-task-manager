"""Natural-language (pt-BR) description of cron expressions.

Examples: "Todos os dias às 08:00 e 17:30", "Toda segunda e quarta às 08:30",
"A cada 15 minutos, de segunda a sexta", "No último dia do mês às 23:00".
"""

from __future__ import annotations

from dataclasses import dataclass

from rts.scheduling.cron import ParsedCron, parse_cron

WEEKDAYS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"]
MONTHS = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]  # fmt: skip

MAX_LISTED_TIMES = 8


def join_pt(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


def _step_of(values: frozenset[int], low: int, high: int) -> int | None:
    """Return n if ``values`` == range(low, high+1, n) with n > 1."""
    ordered = sorted(values)
    if len(ordered) < 2 or ordered[0] != low:
        return None
    step = ordered[1] - ordered[0]
    if step > 1 and ordered == list(range(low, high + 1, step)):
        return step
    return None


def _is_contiguous(values: frozenset[int]) -> bool:
    ordered = sorted(values)
    return ordered == list(range(ordered[0], ordered[-1] + 1))


def _hhmm(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


@dataclass(frozen=True)
class _Parts:
    times: tuple[str, ...] | None  # explicit clock times, when few enough
    interval: str | None  # "A cada 15 minutos" etc.
    days: str | None  # "toda segunda e quarta"; None = every day
    months: str | None  # "em janeiro e julho"


def _weekday_phrase(days: frozenset[int]) -> str:
    if days == frozenset(range(1, 6)):
        return "de segunda a sexta"
    if days == frozenset({0, 6}):
        return "aos sábados e domingos"
    ordered = sorted(days, key=lambda d: (d == 0, d))  # Monday first, Sunday last
    first = ordered[0]
    article = "todo" if first in (0, 6) else "toda"
    return f"{article} {join_pt([WEEKDAYS[d] for d in ordered])}"


def _dom_phrase(p: ParsedCron) -> str:
    labels = [str(d) for d in sorted(p.days)]
    if p.last_day and not labels:
        return "no último dia do mês"
    if p.last_day:
        labels.append("último dia")
    if len(labels) == 1:
        return f"no dia {labels[0]} de cada mês"
    return f"nos dias {join_pt(labels)} de cada mês"


def _day_phrase(p: ParsedCron) -> str | None:
    dom_all = p.dom_star and len(p.days) == 31
    dow_all = p.dow_star and len(p.weekdays) == 7
    if p.dom_star and not dom_all:
        step = _step_of(p.days, 1, 31)
        dom = f"a cada {step} dias" if step else _dom_phrase(p)
    else:
        dom = None if dom_all else _dom_phrase(p)
    dow = None if dow_all or len(p.weekdays) == 7 else _weekday_phrase(p.weekdays)
    if dom and dow:
        # Standard cron: day-of-month OR day-of-week when both are restricted.
        return f"{dom} ou {dow}" if not p.dom_star and not p.dow_star else f"{dom}, {dow}"
    return dom or dow


def _month_phrase(p: ParsedCron) -> str | None:
    if len(p.months) == 12:
        return None
    return "em " + join_pt([MONTHS[m - 1] for m in sorted(p.months)])


def _time_parts(p: ParsedCron) -> tuple[tuple[str, ...] | None, str | None]:
    minutes, hours = p.minutes, p.hours
    all_minutes, all_hours = len(minutes) == 60, len(hours) == 24

    if all_minutes and all_hours:
        return None, "A cada minuto"
    minute_step = _step_of(minutes, 0, 59)
    if minute_step and all_hours:
        return None, f"A cada {minute_step} minutos"
    if len(minutes) == 1:
        (minute,) = minutes
        hour_step = _step_of(hours, min(hours), 23) if len(hours) > 1 else None
        if all_hours:
            return None, "A cada hora" + (f", no minuto {minute}" if minute else "")
        if hour_step and min(hours) == 0:
            return None, f"A cada {hour_step} horas" + (f", no minuto {minute}" if minute else "")
    if len(minutes) * len(hours) <= MAX_LISTED_TIMES:
        return tuple(_hhmm(h, m) for h in sorted(hours) for m in sorted(minutes)), None
    hour_range = (
        f"das {min(hours):02d}h às {max(hours):02d}h"
        if _is_contiguous(hours)
        else "nas horas " + join_pt([f"{h:02d}h" for h in sorted(hours)])
    )
    if all_minutes:
        return None, f"A cada minuto, {hour_range}"
    if minute_step:
        return None, f"A cada {minute_step} minutos, {hour_range}"
    mins = join_pt([str(m) for m in sorted(minutes)])
    return None, f"Nos minutos {mins}, {hour_range}"


def _parts(p: ParsedCron) -> _Parts:
    times, interval = _time_parts(p)
    return _Parts(times, interval, _day_phrase(p), _month_phrase(p))


def _capitalize(text: str) -> str:
    return text[:1].upper() + text[1:]


def _render(parts: _Parts, times: list[str] | None = None) -> str:
    times = times if times is not None else list(parts.times or [])
    suffix = f", {parts.months}" if parts.months else ""
    if times:
        day = parts.days or "todos os dias"
        return f"{_capitalize(day)} às {join_pt(times)}{suffix}"
    text = parts.interval or ""
    if parts.days:
        text += f", {parts.days}"
    return text + suffix


def describe(expressions: list[str]) -> str:
    """Describe one or more cron expressions. Raises CronError if any is invalid."""
    if not expressions:
        return "Sem agendamento (apenas execução manual)"
    all_parts = [_parts(parse_cron(e)) for e in expressions]

    # Merge "same days, different times" into a single sentence.
    rendered: list[str] = []
    merged: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    for parts in all_parts:
        if parts.times:
            key = (parts.days, parts.months)
            if key not in merged:
                merged[key] = []
                order.append(key)
            merged[key].extend(t for t in parts.times if t not in merged[key])
        else:
            rendered.append(_render(parts))
    timed = []
    for key in order:
        days, months = key
        times = sorted(merged[key])
        timed.append(_render(_Parts(tuple(times), None, days, months), times))
    return "; ".join(timed + rendered)
