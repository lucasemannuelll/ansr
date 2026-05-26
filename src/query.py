# --- IMPORTS ---

import sqlite3
import sys
from datetime import datetime, timezone

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# --- GLOBALS ---

console = Console()

DB_PATH: str = "results.db"


# --- DATABASE HELPERS ---


def get_connection() -> sqlite3.Connection:
    """Open a connection to results.db, exiting gracefully if it doesn't exist."""
    import os
    if not os.path.exists(DB_PATH):
        console.print(
            Panel(
                f"[yellow]No database found at [bold]{DB_PATH}[/].\n"
                "Run the grader first to record some results.[/]",
                title="[bold red]No Data[/]",
                border_style="red",
            )
        )
        sys.exit(0)
    return sqlite3.connect(DB_PATH)


def ensure_table_exists(conn: sqlite3.Connection) -> bool:
    """Return True if the results table exists and has at least one row."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='results'"
    )
    if cur.fetchone() is None:
        return False
    cur = conn.execute("SELECT COUNT(*) FROM results")
    return cur.fetchone()[0] > 0


# --- SCORE STYLING ---


def score_color(score_pct: float) -> str:
    if score_pct >= 70:
        return "bold green"
    elif score_pct >= 50:
        return "bold yellow"
    return "bold red"


def verdict(score_pct: float) -> str:
    if score_pct >= 70:
        return "Good"
    elif score_pct >= 50:
        return "Okay"
    return "Bad"


def fmt_score(score_pct: float) -> str:
    color = score_color(score_pct)
    return f"[{color}]{score_pct:.1f}%[/]"


def fmt_timestamp(iso: str) -> str:
    """Convert an ISO-8601 UTC string to a local-friendly display string."""
    try:
        dt = datetime.fromisoformat(iso)
        # Convert to local time for display
        dt_local = dt.astimezone()
        return dt_local.strftime("%Y-%m-%d  %H:%M")
    except Exception:
        return iso


# --- DISPLAY SECTIONS ---


def display_global_summary(conn: sqlite3.Connection, subject_filter: str | None) -> None:
    where = "WHERE subject = ?" if subject_filter else ""
    params = (subject_filter,) if subject_filter else ()

    row = conn.execute(
        f"""
        SELECT
            COUNT(*)              AS total_exams,
            AVG(score_pct)        AS avg_score,
            MAX(score_pct)        AS best_score,
            MIN(score_pct)        AS worst_score,
            SUM(correct)          AS total_correct,
            SUM(total)            AS total_questions
        FROM results {where}
        """,
        params,
    ).fetchone()

    total_exams, avg_score, best_score, worst_score, total_correct, total_questions = row

    title = (
        f"[bold]Global Summary — {subject_filter}[/]"
        if subject_filter
        else "[bold]Global Summary[/]"
    )

    summary_text = (
        f"[white]Total exams recorded:[/]   [bold]{total_exams}[/]\n"
        f"[white]Questions answered:[/]     [bold]{total_correct}[/] / [bold]{total_questions}[/]\n"
        f"[white]Overall average score:[/]  {fmt_score(avg_score)}\n"
        f"[white]Best score:[/]             {fmt_score(best_score)}\n"
        f"[white]Worst score:[/]            {fmt_score(worst_score)}"
    )

    console.print(
        Panel(summary_text, title=title, border_style="cyan", expand=False)
    )
    console.print()


def display_subject_breakdown(conn: sqlite3.Connection, subject_filter: str | None) -> None:
    where = "WHERE subject = ?" if subject_filter else ""
    params = (subject_filter,) if subject_filter else ()

    rows = conn.execute(
        f"""
        SELECT
            subject,
            COUNT(*)        AS attempts,
            AVG(score_pct)  AS avg_score,
            MAX(id)         AS last_id
        FROM results {where}
        GROUP BY subject
        ORDER BY avg_score DESC
        """,
        params,
    ).fetchall()

    # Fetch last attempt score for each subject to compute trend
    last_scores: dict[str, float] = {}
    for subject, *_ in rows:
        last_row = conn.execute(
            "SELECT score_pct FROM results WHERE subject = ? ORDER BY id DESC LIMIT 1",
            (subject,),
        ).fetchone()
        if last_row:
            last_scores[subject] = last_row[0]

    table = Table(
        title="[bold]Subject Breakdown[/]",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("Subject",   style="bold white")
    table.add_column("Attempts",  justify="center")
    table.add_column("Avg Score", justify="center")
    table.add_column("Last Score",justify="center")
    table.add_column("Trend",     justify="center")

    for subject, attempts, avg_score, _last_id in rows:
        last = last_scores.get(subject, avg_score)
        if attempts == 1 or abs(last - avg_score) < 0.1:
            trend = "[dim]—[/]"
        elif last > avg_score:
            trend = "[bold green]↑ Improving[/]"
        else:
            trend = "[bold red]↓ Declining[/]"

        table.add_row(
            subject,
            str(attempts),
            fmt_score(avg_score),
            fmt_score(last),
            trend,
        )

    console.print(table)
    console.print()


def display_insights(conn: sqlite3.Connection, subject_filter: str | None) -> None:
    where = "WHERE subject = ?" if subject_filter else ""
    params = (subject_filter,) if subject_filter else ()

    rows = conn.execute(
        f"""
        SELECT subject, AVG(score_pct) AS avg_score
        FROM results {where}
        GROUP BY subject
        ORDER BY avg_score DESC
        """,
        params,
    ).fetchall()

    if not rows:
        return

    strongest = rows[0]
    needs_focus = [r for r in rows if r[1] < 60.0]

    lines = []
    lines.append(
        f"[white]Strongest subject:[/]  [bold green]{strongest[0]}[/] "
        f"({fmt_score(strongest[1])} avg)"
    )

    if needs_focus:
        subjects_str = ", ".join(
            f"[bold red]{r[0]}[/] ({fmt_score(r[1])})" for r in needs_focus
        )
        lines.append(f"[white]Needs focus (< 60%):[/] {subjects_str}")
    else:
        lines.append("[white]Needs focus:[/] [dim]None — all subjects above 60% ✓[/]")

    console.print(
        Panel(
            "\n".join(lines),
            title="[bold]Insights[/]",
            border_style="magenta",
            expand=False,
        )
    )
    console.print()


def display_history(conn: sqlite3.Connection, subject_filter: str | None, limit: int = 10) -> None:
    where = "WHERE subject = ?" if subject_filter else ""
    params: tuple = (subject_filter,) if subject_filter else ()

    rows = conn.execute(
        f"""
        SELECT id, timestamp, subject, total, correct, wrong, score_pct
        FROM results {where}
        ORDER BY id DESC
        LIMIT {limit}
        """,
        params,
    ).fetchall()

    title = (
        f"[bold]Last {limit} Attempts — {subject_filter}[/]"
        if subject_filter
        else f"[bold]Last {limit} Attempts[/]"
    )

    table = Table(
        title=title,
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold magenta",
    )
    table.add_column("#",        justify="center", style="dim")
    table.add_column("Date & Time",  justify="center")
    table.add_column("Subject",  style="bold white")
    table.add_column("Total",    justify="center")
    table.add_column("Correct",  justify="center")
    table.add_column("Wrong",    justify="center")
    table.add_column("Score",    justify="center")
    table.add_column("Verdict",  justify="center")

    for row_id, timestamp, subject, total, correct, wrong, score_pct in rows:
        color = score_color(score_pct)
        table.add_row(
            str(row_id),
            fmt_timestamp(timestamp),
            subject,
            str(total),
            f"[green]{correct}[/]",
            f"[red]{wrong}[/]",
            fmt_score(score_pct),
            f"[{color}]{verdict(score_pct)}[/]",
        )

    console.print(table)
    console.print()


# --- CLI ENTRY POINT ---


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--subject", "-s",
    default=None,
    metavar="SUBJECT",
    help="Filter all views to a specific subject.",
)
@click.option(
    "--history", "-H",
    is_flag=True,
    default=False,
    help="Show the last 10 exam attempts.",
)
def main(subject: str | None, history: bool) -> None:
    """Analytics dashboard for ansr — query past exam performance."""

    conn = get_connection()

    if not ensure_table_exists(conn):
        console.print(
            Panel(
                "[yellow]The results table is empty.\n"
                "Run the grader first to record some results.[/]",
                title="[bold red]No Data[/]",
                border_style="red",
            )
        )
        conn.close()
        sys.exit(0)

    # Validate subject filter if provided
    if subject:
        exists = conn.execute(
            "SELECT 1 FROM results WHERE subject = ? LIMIT 1", (subject,)
        ).fetchone()
        if not exists:
            console.print(
                f"[bold red]No results found for subject:[/] [yellow]{subject}[/]\n"
                "[dim]Use the dashboard without --subject to see all subjects.[/]"
            )
            conn.close()
            sys.exit(0)

    console.print()
    display_global_summary(conn, subject)
    display_subject_breakdown(conn, subject)
    display_insights(conn, subject)

    if history:
        display_history(conn, subject)

    conn.close()


if __name__ == "__main__":
    main()
