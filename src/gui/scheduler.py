import datetime

from utils.utils import round_time_to_minutes


def calculate_next_run(
    days: list[int],
    times: list[str],
    now: datetime.datetime | None = None,
    last_run: datetime.datetime | None = None,
) -> datetime.datetime | None:
    """
    Calculate the next scheduled execution timestamp based on active days and times.

    Optimized direct calculation replacing the legacy 10,080-minute brute-force loop.

    :param days: List of integer weekdays (0 = Monday, ..., 6 = Sunday).
    :param times: List of "HH:MM" string times.
    :param now: Current reference time (defaults to datetime.datetime.now()).
    :param last_run: Timestamp of the most recent completed execution to prevent immediate re-triggering.
    :return: Earliest upcoming datetime within the next 7 days, or None if schedule is empty or invalid.
    """
    if not days or not times:
        return None

    if now is None:
        now = datetime.datetime.now()

    now_rounded = round_time_to_minutes(now)

    # Parse and sort valid HH:MM times
    parsed_times: list[tuple[int, int]] = []
    for t_str in times:
        try:
            parts = str(t_str).strip().split(':')
            if len(parts) == 2:
                hour = int(parts[0])
                minute = int(parts[1])
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    parsed_times.append((hour, minute))
        except (ValueError, TypeError):
            continue

    if not parsed_times:
        return None

    parsed_times.sort()
    last_run_rounded = round_time_to_minutes(last_run) if last_run is not None else None

    # Check candidates over the next 8 days (covering full 7-day wrap-around)
    candidates: list[datetime.datetime] = []
    base_date = now_rounded.date()

    for day_offset in range(8):
        target_date = base_date + datetime.timedelta(days=day_offset)
        if target_date.weekday() in days:
            for hour, minute in parsed_times:
                candidate_dt = datetime.datetime(
                    target_date.year,
                    target_date.month,
                    target_date.day,
                    hour,
                    minute,
                )
                # Skip past times on today's date
                if candidate_dt < now_rounded:
                    continue
                # If candidate matches the current minute, only skip if already executed
                if candidate_dt == now_rounded and last_run_rounded is not None and last_run_rounded >= candidate_dt:
                    continue

                candidates.append(candidate_dt)

    if not candidates:
        return None

    return min(candidates)
