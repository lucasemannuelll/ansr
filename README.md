# ansr
CLI tool for grading multiple choice tests and tracking performance.

## Usage

### Grading
```bash
python src/ansr.py answers.csv # interactive mode
python src/ansr.py answers.csv student.csv # file mode
```
Results are automatically saved to `results.db`.

### Analytics
```bash
python src/query.py # global summary
python src/query.py --history # show last 10 attempts
python src/query.py --subject "Math" # filter by subject
```

## Data Format
CSV with no header: `question_number,answer`

```csv
1,A
2,C
3,-
```
Valid answers: `A, B, C, D, E` and `-` (unanswered).

## Requirements
- `rich`
- `click`
- `sqlite3` (built-in)
