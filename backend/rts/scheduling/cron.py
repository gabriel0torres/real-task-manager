"""Standard 5-field cron parsing, validation and next-run computation.

We parse cron ourselves (instead of ``CronTrigger.from_crontab``) because:

* APScheduler 3.x numbers ``day_of_week`` as 0=Monday, standard cron uses 0=Sunday;
* standard cron supports ``L`` (last day of month), APScheduler calls it ``last``;
* standard (Vixie) cron fires when *either* day-of-month or day-of-week matches if
  both are restricted, while APScheduler requires both.

Each expression is validated and translated into one or two explicit APScheduler
``CronTrigger`` objects; several expressions are combined with ``OrTrigger``. The
same trigger is used both for the UI preview and by the execution engine, so they
can never disagree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

MAX_EXPRESSIONS = 50

MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
DOW_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

# Max days per month (February allows 29 so leap years are reachable).
_MONTH_DAYS = {
    1: 31,
    2: 29,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}


class CronError(ValueError):
    """Invalid cron expression or timezone (message is user-facing, pt-BR)."""


@dataclass(frozen=True)
class _FieldSpec:
    label: str
    low: int
    high: int
    names: list[str] | None = None
    name_offset: int = 0


_FIELDS = (
    _FieldSpec("minuto", 0, 59),
    _FieldSpec("hora", 0, 23),
    _FieldSpec("dia do mês", 1, 31),
    _FieldSpec("mês", 1, 12, MONTH_NAMES, 1),
    _FieldSpec("dia da semana", 0, 7, DOW_NAMES, 0),
)

_TOKEN_RE = re.compile(r"^(?P<range>\*|[a-z0-9]+(?:-[a-z0-9]+)?)(?:/(?P<step>\d+))?$")


@dataclass(frozen=True)
class ParsedCron:
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    last_day: bool
    months: frozenset[int]
    weekdays: frozenset[int]  # 0=Sunday ... 6=Saturday
    dom_star: bool
    dow_star: bool


def _value(raw: str, spec: _FieldSpec) -> int:
    if spec.names and raw in spec.names:
        return spec.names.index(raw) + spec.name_offset
    if not raw.isdigit():
        raise CronError(f"Valor inválido '{raw}' no campo {spec.label}.")
    value = int(raw)
    if not spec.low <= value <= spec.high:
        raise CronError(
            f"Valor {value} fora do intervalo {spec.low}-{spec.high} no campo {spec.label}."
        )
    return value


def _parse_field(field: str, spec: _FieldSpec) -> tuple[set[int], bool]:
    """Return (values, has_last). ``has_last`` only applies to day-of-month."""
    values: set[int] = set()
    has_last = False
    for token in field.split(","):
        if not token:
            raise CronError(f"Lista malformada no campo {spec.label}.")
        if token == "l" and spec.label == "dia do mês":
            has_last = True
            continue
        match = _TOKEN_RE.match(token)
        if not match:
            raise CronError(f"Trecho inválido '{token}' no campo {spec.label}.")
        rng, step_raw = match.group("range"), match.group("step")
        step = int(step_raw) if step_raw else 1
        if step < 1:
            raise CronError(f"Passo deve ser maior que zero no campo {spec.label}.")
        if rng == "*":
            start, end = spec.low, spec.high
        elif "-" in rng:
            a, b = rng.split("-", 1)
            start, end = _value(a, spec), _value(b, spec)
            if start > end:
                raise CronError(f"Intervalo invertido '{rng}' no campo {spec.label}.")
        else:
            start = _value(rng, spec)
            # "a/n" means "from a to the end, every n" (Vixie cron).
            end = spec.high if step_raw else start
        values.update(range(start, end + 1, step))
    return values, has_last


def parse_cron(expression: str) -> ParsedCron:
    normalized = " ".join(expression.strip().lower().split())
    if not normalized:
        raise CronError("Expressão cron vazia.")
    normalized = MACROS.get(normalized, normalized)
    parts = normalized.split(" ")
    if len(parts) != 5:
        raise CronError(
            f"A expressão deve ter 5 campos (minuto hora dia mês dia-da-semana); "
            f"foram encontrados {len(parts)}."
        )
    parsed = [_parse_field(field, spec) for field, spec in zip(parts, _FIELDS, strict=True)]
    (minutes, _), (hours, _), (days, last_day), (months, _), (dows, _) = parsed
    weekdays = {d % 7 for d in dows}  # 7 -> Sunday

    dom_star = parts[2].startswith("*")
    dow_star = parts[4].startswith("*")
    result = ParsedCron(
        # Canonical form keeps the conventional upper-case "L" (last day of month).
        expression=" ".join([*parts[:2], parts[2].replace("l", "L"), *parts[3:]]),
        minutes=frozenset(minutes),
        hours=frozenset(hours),
        days=frozenset(days),
        last_day=last_day,
        months=frozenset(months),
        weekdays=frozenset(weekdays),
        dom_star=dom_star,
        dow_star=dow_star,
    )
    _check_reachable(result)
    return result


def _check_reachable(p: ParsedCron) -> None:
    # With both day fields restricted the OR semantics always yields a match.
    if p.dom_star or not p.dow_star or p.last_day:
        return
    if not any(day <= _MONTH_DAYS[m] for day in p.days for m in p.months):
        raise CronError("A expressão nunca será executada (dia inexistente nos meses escolhidos).")


def normalize_expression(expression: str) -> str:
    """Validate and return the canonical (lower-case, single-spaced) form."""
    return parse_cron(expression).expression


def get_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"Fuso horário desconhecido: '{name}'.") from exc


def _join(values: frozenset[int], full: range) -> str:
    if set(full) <= values:
        return "*"
    return ",".join(str(v) for v in sorted(values))


def _triggers_for(p: ParsedCron, tz: ZoneInfo) -> list[CronTrigger]:
    minute = _join(p.minutes, range(0, 60))
    hour = _join(p.hours, range(0, 24))
    month = _join(p.months, range(1, 13))
    day_parts = [str(d) for d in sorted(p.days)] + (["last"] if p.last_day else [])
    day = "*" if p.dom_star else ",".join(day_parts)
    dow = "*" if p.dow_star else ",".join(DOW_NAMES[d] for d in sorted(p.weekdays))

    def make(day_expr: str, dow_expr: str) -> CronTrigger:
        return CronTrigger(
            minute=minute, hour=hour, day=day_expr, month=month, day_of_week=dow_expr, timezone=tz
        )

    if not p.dom_star and not p.dow_star:
        # Vixie semantics: day-of-month OR day-of-week.
        return [make(day, "*"), make("*", dow)]
    return [make(day, dow)]


def build_trigger(expressions: list[str], timezone: str) -> BaseTrigger:
    if not expressions:
        raise CronError("Informe pelo menos uma expressão de agendamento.")
    if len(expressions) > MAX_EXPRESSIONS:
        raise CronError(f"Máximo de {MAX_EXPRESSIONS} expressões por tarefa.")
    tz = get_timezone(timezone)
    triggers: list[CronTrigger] = []
    for expr in expressions:
        triggers.extend(_triggers_for(parse_cron(expr), tz))
    return triggers[0] if len(triggers) == 1 else OrTrigger(triggers)


def fire_times_between(
    expressions: list[str], timezone: str, start: datetime, end: datetime, limit: int = 1000
) -> list[datetime]:
    """Fire times in the interval ``(start, end]`` (start exclusive), at most ``limit`` items."""
    trigger = build_trigger(expressions, timezone)
    tz = get_timezone(timezone)
    # Cron fires on whole minutes, so +1s makes the start exclusive.
    now = (start + timedelta(seconds=1)).astimezone(tz)
    result: list[datetime] = []
    previous: datetime | None = None
    while len(result) < limit:
        nxt = trigger.get_next_fire_time(previous, now)
        if nxt is None or nxt > end:
            break
        result.append(nxt)
        previous = now = nxt
    return result


def next_fire_times(
    expressions: list[str], timezone: str, count: int = 5, after: datetime | None = None
) -> list[datetime]:
    """Next ``count`` fire times at or after ``after`` (default: now), in the task timezone."""
    trigger = build_trigger(expressions, timezone)
    tz = get_timezone(timezone)
    now = (after or datetime.now(tz)).astimezone(tz)
    result: list[datetime] = []
    previous: datetime | None = None
    for _ in range(count):
        nxt = trigger.get_next_fire_time(previous, now)
        if nxt is None:
            break
        result.append(nxt)
        previous = now = nxt
    return result
