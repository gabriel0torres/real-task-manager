from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from rts.scheduling.cron import CronError, next_fire_times, normalize_expression, parse_cron

TZ = "America/Sao_Paulo"
# Monday, 16 Nov 2026, 10:00 in São Paulo
NOW = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo(TZ))


def fmt(expressions, count=5, tz=TZ, after=NOW):
    return [d.strftime("%a %Y-%m-%d %H:%M") for d in next_fire_times(expressions, tz, count, after)]


def test_weekdays_with_time():
    assert fmt(["30 8 * * 1,3"], 3) == [
        "Wed 2026-11-18 08:30",
        "Mon 2026-11-23 08:30",
        "Wed 2026-11-25 08:30",
    ]


@pytest.mark.parametrize("sunday", ["0", "7", "sun", "SUN"])
def test_sunday_aliases(sunday):
    assert fmt([f"0 9 * * {sunday}"], 1) == ["Sun 2026-11-22 09:00"]


def test_weekday_range_including_sunday():
    # 0-2 = Sun, Mon, Tue (standard cron numbering, not APScheduler's)
    assert fmt(["0 12 * * 0-2"], 3) == [
        "Mon 2026-11-16 12:00",
        "Tue 2026-11-17 12:00",
        "Sun 2026-11-22 12:00",
    ]


def test_multiple_expressions_are_merged_in_order():
    assert fmt(["0 8 * * *", "30 17 * * *"], 4) == [
        "Mon 2026-11-16 17:30",
        "Tue 2026-11-17 08:00",
        "Tue 2026-11-17 17:30",
        "Wed 2026-11-18 08:00",
    ]


def test_last_day_of_month():
    assert fmt(["0 9 L * *"], 4) == [
        "Mon 2026-11-30 09:00",
        "Thu 2026-12-31 09:00",
        "Sun 2027-01-31 09:00",
        "Sun 2027-02-28 09:00",
    ]


def test_dom_and_dow_use_or_semantics_like_standard_cron():
    # Day 13 OR Friday
    assert fmt(["0 0 13 * 5"], 5)[-1] == "Sun 2026-12-13 00:00"
    assert "Fri 2026-11-20 00:00" in fmt(["0 0 13 * 5"], 5)


def test_steps_and_ranges():
    assert fmt(["*/20 10-11 * * *"], 6) == [
        "Mon 2026-11-16 10:00",
        "Mon 2026-11-16 10:20",
        "Mon 2026-11-16 10:40",
        "Mon 2026-11-16 11:00",
        "Mon 2026-11-16 11:20",
        "Mon 2026-11-16 11:40",
    ]
    # "a/n" = from a to the end, every n
    assert parse_cron("5/20 * * * *").minutes == frozenset({5, 25, 45})


def test_month_names_and_macros():
    assert normalize_expression("  0  0 1 JAN *  ") == "0 0 1 jan *"
    assert normalize_expression("@daily") == "0 0 * * *"
    assert fmt(["@monthly"], 1) == ["Tue 2026-12-01 00:00"]


def test_timezone_is_respected():
    utc_runs = next_fire_times(["0 8 * * *"], "UTC", 1, NOW)
    sp_runs = next_fire_times(["0 8 * * *"], TZ, 1, NOW)
    assert utc_runs[0].utcoffset().total_seconds() == 0
    assert sp_runs[0].strftime("%H:%M") == "08:00"
    assert sp_runs[0].utcoffset().total_seconds() == -3 * 3600


@pytest.mark.parametrize(
    ("expr", "message"),
    [
        ("", "vazia"),
        ("* * * *", "5 campos"),
        ("60 * * * *", "fora do intervalo 0-59 no campo minuto"),
        ("0 24 * * *", "campo hora"),
        ("0 0 0 * *", "campo dia do mês"),
        ("0 0 * 13 *", "campo mês"),
        ("0 0 * * 8", "campo dia da semana"),
        ("0 0 * * foo", "Valor inválido 'foo'"),
        ("5-1 * * * *", "Intervalo invertido"),
        ("*/0 * * * *", "Passo"),
        ("1,,2 * * * *", "Lista malformada"),
        ("0 0 31 2 *", "nunca será executada"),
        ("0 0 L * 1-5x", "dia da semana"),
    ],
)
def test_invalid_expressions(expr, message):
    with pytest.raises(CronError, match=message):
        parse_cron(expr)


def test_invalid_timezone():
    with pytest.raises(CronError, match="Fuso horário desconhecido"):
        next_fire_times(["0 0 * * *"], "Mars/Olympus", 1)


def test_empty_expression_list_rejected():
    with pytest.raises(CronError, match="pelo menos uma"):
        next_fire_times([], TZ, 1)
