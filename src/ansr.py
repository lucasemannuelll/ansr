# --- IMPORTS ---

import csv
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

# --- GLOBALS --

console = Console()

DB_PATH: str = "results.db"

VALID = {"A", "B", "C", "D", "E" , "-"}


# --- DATABASE ---


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            subject   TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            total     INTEGER NOT NULL,
            correct   INTEGER NOT NULL,
            wrong     INTEGER NOT NULL,
            score_pct REAL NOT NULL
        ) STRICT;
    """)

    conn.commit()

def save_to_database(
        conn: sqlite3.Connection, subject: str,
        total: int, correct: int,
        wrong: int, score_pct: float
        ) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    conn.execute("""
                 INSERT INTO results (timestamp, subject, total, correct, wrong, score_pct)
                 VALUES (?, ?, ?, ?, ?, ?)
                 """, (timestamp, subject, total, correct, wrong, score_pct),
    )
    conn.commit()


# --- CSV Helpers ---

def parse_csv(file_path: str, source_path: str) -> dict[str, str]:
    target_path = Path(file_path)

    if not target_path.exists():
        console.print(f"[bold red]File not found:[/] [yellow]{file_path}[/]")
        sys.exit(1)

    parsed_answers: dict[str, str] = {}

    with target_path.open(newline="", encoding="utf-8") as csv_file:
        for line_num, row in enumerate(csv.reader(csv_file), start=1):
            row_data = [cell.strip() for cell in row]

            if not any(row_data):
                continue

            if len(row_data) < 2:
                console.print(f"[bold red]Malformed row[/] in [yellow]{source_path}[/] "
                              f"at line {line_num}: expected 2 columns, got {len(row_data)}.")
                sys.exit(1)

            question_id = row_data[0]
            answer = row_data[1].upper()

            if answer not in VALID:
                console.print(f"[bold red]Invalid answer '{answer}' in [yellow]{source_path}[/] "
                              f"at line {line_num}")
                sys.exit(1)

            if not question_id:
                console.print(f"[bold red]Empty question number[/] in [yellow]{source_path}[/] "
                              f"at line {line_num}.")
                sys.exit(1)

            if question_id in parsed_answers:
                console.print(f"[bold red]Duplicate question ID '{question_id}'[/] [yellow]{source_path}[/] "
                              f"at line {line_num}.")
                sys.exit(1)

            parsed_answers[question_id] = answer

    if not parsed_answers:
        console.print(f"[yellow]{source_path}[/] is empty.")
        sys.exit(1)

    return parsed_answers

def collect_interactive(question_ids: list[str]) -> dict[str, str]:
    console.print(
        Panel("[bold white]Enter the student's answers[/]\n"
             "Type the answer letter (e.g [bold]A[/], [bold]B[/], [bold]C[/], [bold]D[/], [bold]E[/])\n"
              "for each question, then press enter.\n"
              "Leave blank and press Enter to mark a question as not answered ([bold]-[/]).",
              title="[bold]Student Answers[/]",
              border_style="cyan",
        )
    )

    answers: dict[str, str] = {}
 
    for question_id in question_ids:
        while True:
            try:
                user_answer = Prompt.ask(f" Q{question_id}").strip().upper() or "-"
            except (KeyboardInterrupt, EOFError):
                console.print("\n[yellow]Input interrupted[/]")
                sys.exit(1)
            if user_answer in VALID:
                break
            console.print(f"[red]Invalid answer [bold]'{user_answer}'[/]")
        answers[question_id] = user_answer
 
    return answers

# --- GRADING ---

# returns: (graded_rows, correct_count, wrong_count, score_pct)
def grade(answer_key: dict[str, str], student_answers: dict[str, str]):
    graded_rows = []
    correct_count = 0

    for question_id, correct_answer in answer_key.items():
        student_answer = student_answers.get(question_id, "Missing")
        is_correct = (student_answer == correct_answer)
        if is_correct:
            correct_count += 1
        graded_rows.append((question_id, correct_answer, student_answer, is_correct))

    total_questions = len(answer_key)
    wrong_count = total_questions - correct_count
    score_pct = ((correct_count / total_questions) * 100) if total_questions else 0.0

    return graded_rows, correct_count, wrong_count, score_pct


# --- RICH OUTPUT ---

def display_results(graded_rows, correct_count, wrong_count, total_questions, score_pct, subject_name):
    results_table = Table(
        title=f"[bold]Results - {subject_name}[/]",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold magenta",
    )
    results_table.add_column("Q#", justify="center", style="dim")
    results_table.add_column("Correct Answer", justify="center")
    results_table.add_column("Student Answer", justify="center")
    results_table.add_column("Status", justify="center")

    for question_id, correct_answer, student_answers, is_correct in graded_rows:
        status_mark = "[bold green]✓[/]" if is_correct else "[bold red]✗[/]"
        text_color  = "green" if is_correct else "red"
        results_table.add_row(
            question_id,
            f"[bold]{correct_answer}[/]",
            f"[{text_color}]{student_answers}[/]",
            status_mark,
        )

    console.print()
    console.print(results_table)

    if score_pct >= 70:
        theme_color = "bold green"
        verdict = "Good"
    elif score_pct >= 50:
        theme_color = "bold yellow"
        verdict = "Okay"
    else:
        theme_color = "bold red"
        verdict = "Bad"

    summary_text = (
        f"[white]Total questions:[/] [bold]{total_questions}[/]\n"
        f"[green]Correct:[/] [bold green]{correct_count}[/]\n"
        f"[red]Wrong:[/] [bold red]{wrong_count}[/]\n"
        f"[white]Score:[/] [{theme_color}]{score_pct:.1f}%[/] "
        f"[{theme_color}]{verdict}[/]"
    )

    console.print(
        Panel(summary_text, title="[bold]Summary[/]", border_style="bold green")
    )
    console.print()


# --- MAIN + CLI ENTRY POINT ---

@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("answer_key_path", metavar="ANSWER_KEY_CSV", type=click.Path())
@click.argument("student_answer_path", metavar="[STUDENT_ANSWER_CSV]", required=False, default=None)
def main(answer_key_path: str, student_answer_path: str | None):
    answer_key = parse_csv(answer_key_path, "answer key")

    if student_answer_path:
        student_answers = parse_csv(student_answer_path, "student answers")

        unanswered_questions = [q for q in answer_key if q not in student_answers]
        if unanswered_questions:
            console.print(f"[yellow]{len(unanswered_questions)} question(s) missing from student file: "
                          f"{', '.join(unanswered_questions)}[/]")
            sys.exit(1)

        extra_questions = [q for q in student_answers if q not in answer_key]
        if extra_questions:
            console.print(f"[yellow]{len(extra_questions)} question(s) in student file not answer key: "
                          f"{', '.join(extra_questions)}[/]")
            sys.exit(1)

    else:
        student_answers = collect_interactive(list(answer_key))

    console.print()
    exam_title = Prompt.ask("[bold cyan]Subject / exam name[/]").strip().title() or "Generic Exam"

    graded_rows, correct_count, wrong_count, score_pct = grade(answer_key, student_answers)

    display_results(
        graded_rows,
        correct_count,
        wrong_count,
        len(answer_key),
        score_pct,
        exam_title
    )

    try:
        with sqlite3.connect(DB_PATH) as conn:
            init_db(conn)
            save_to_database(conn, exam_title, len(answer_key), correct_count, wrong_count, score_pct)
        console.print(f"[dim]Session saved to [bold]{DB_PATH}[/]\n")
    except sqlite3.Error as e:
        console.print(f"[bold red]Database error: [/] {e}")


if __name__ == "__main__":
    main()
