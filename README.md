# grz_query_metadata

Survey which metadata values are actually used across GRZ submissions, so that
proposed changes to the [GRZ metadata schema](https://github.com/BfArM-MVH/MVGenomseq_GRZ)
can be decided on evidence rather than assumption.

The proposal these questions are aimed at is
[MVGenomseq PR #1 — *Revise GRZ metadata schema for 2.0.0*](https://github.com/jblesch/MVGenomseq/pull/1),
called **the schema proposal** throughout this README.

Each GRZ runs `survey_grz_metadata.py` against its own submission database and
returns a small JSON report. Those reports are combined with
`aggregate_grz_surveys.py` into a single spreadsheet.

Typical questions this answers:

- How often is `wxs` used? It has been discussed if wxs is really needed, also because relationship to wes is unclear
- How many submissions use an ontology other than BRENDA in `tissueOntology`?
- Is `reverse` in `sequencingLayout` ever used at all?
- Do the free-text `libraryPrepKit` and `sequencerModel` values in use today map
  onto the controlled vocabularies **proposed in the schema proposal**, and what
  share of real submissions would fail if those vocabularies were adopted as
  drafted? The unmatched values are the list of entries still to be added.

## What the script does to your database

**It reads. It never writes.** The script issues exactly one statement:

```sql
SELECT id, submission_metadata FROM submissions
```

It then inspects the metadata JSON in Python. No JSON-path SQL is used, so the
same code runs unchanged against SQLite and PostgreSQL.

### What leaves your site

The report contains **counts of values**, plus the distinct values found in
technical fields such as kit and instrument names — that is what makes the
vocabulary comparison possible.

The following are never read and never appear in the output:

| Never touched |
|---|
| `tanG` |
| `donorPseudonym`, `pseudonym` |
| `localCaseId` |
| `filePath`, `fileChecksum` |
| any date field |
| submission ids |

One field deserves a look before you send anything: `labDataName` is free text
and could in principle contain something identifying, for example
`"Blut DNA Müller"`. Run with `--redact-freetext` to report only counts for all
free-text fields, or simply open the JSON and check. The script reminds you on
every run.

## Requirements

- Python 3.11+
- `sqlalchemy` — already present in the `grz_tools` environment
- `PyYAML` — only if you use `--config-file`
- `openpyxl` — only for the aggregation step, which the coordinator runs

No installation step. Both files are standalone scripts.

## Running the survey

```bash
# SQLite: a plain path is fine
python survey_grz_metadata.py --db-url /path/to/submission.db.sqlite

# PostgreSQL
python survey_grz_metadata.py --db-url postgresql://user@host/grzdb

# or take the URL from your grz config file
python survey_grz_metadata.py --config-file /etc/grz/config.yaml
```

This writes `grz-survey-<date>.json` in the working directory.

Useful flags:

| Flag | Effect |
|---|---|
| `--redact-freetext` | report counts only for free-text fields, not their values |
| `--out FILE` | write somewhere other than the default filename |
| `--grz-id ID` | label the report with your site id (optional, see below) |
| `--max-freetext-values N` | keep only the N most common values per field (default 500) |

**`--grz-id` is optional.** It does nothing except name the report file and label
your column in the aggregated workbook. If you omit it, the report is named after
the date alone and the aggregation step falls back to the filename, so each site
still gets its own column. Pass it only if you want the columns labelled with
real GRZ ids rather than filenames.

**`--max-freetext-values` is a size cap, not a sampling limit.** Everything is
counted; the flag only limits how much of the tail is written out. Values are
sorted by frequency and the N most common are kept, so the field's `_total` and
`_distinct` figures stay exact regardless, and any field that lost values is
marked `"_truncated": true`. The default of 500 exists because a free-text field
like `labDataName` can hold thousands of one-off values that would bloat the
report without changing any decision — the rare tail is by definition not what
a controlled vocabulary needs to cover. Raise it if you want the complete list;
`--max-freetext-values 0` is not useful, since it would keep nothing.


## Aggregating the reports

Run by whoever collects the reports:

```bash
python aggregate_grz_surveys.py grz-survey-*.json -o schema-usage.xlsx
```

To also measure how well a proposed controlled vocabulary would cover the
free-text values actually in use:

```bash
python aggregate_grz_surveys.py grz-survey-*.json -o schema-usage.xlsx \
    --vocab labData.sequencerModel=path/to/instrument-model.json \
    --vocab labData.libraryPrepKit=path/to/library-preparation-kit-retail-name.json
```

Both vocabulary files come from the schema proposal itself — they are added by
[PR #1](https://github.com/jblesch/MVGenomseq/pull/1) and live in
`GRZ/vocabularies/` on its `dev` branch:

| File | Compared against |
|---|---|
| [`GRZ/vocabularies/instrument-model.json`](https://github.com/jblesch/MVGenomseq/blob/dev/GRZ/vocabularies/instrument-model.json) | the free-text `sequencerModel` values in use today |
| [`GRZ/vocabularies/library-preparation-kit-retail-name.json`](https://github.com/jblesch/MVGenomseq/blob/dev/GRZ/vocabularies/library-preparation-kit-retail-name.json) | the free-text `libraryPrepKit` values in use today |

So the coverage figure answers a question about the proposal specifically: if
these two fields became closed enums as drafted, what share of what the GRZs
have already submitted would still validate.

### Finding the values nobody uses

The survey counts what it sees, so an enum value that never occurs is simply
absent from the report. That is a problem, because "never used by anyone" is
precisely the finding that justifies dropping a value. Pass the schema and those
gaps are filled in:

```bash
python aggregate_grz_surveys.py grz-survey-*.json -o schema-usage.xlsx \
    --schema path/to/grz-schema.json
```

This reads the enum declared at each surveyed path — following `$ref` into
`GRZ/vocabularies/` where needed — and adds a row at zero for every declared
value no GRZ used. Each sheet then shows the complete vocabulary instead of only
the part in use. Rows are colour-coded:

| Colour | Meaning |
|---|---|
| blue | declared in the schema, **never used by anyone** — a candidate for removal |
| amber | outside the proposed vocabulary, where `--vocab` was also given |

A value present in the data but absent from the schema is **not** flagged as a
problem. Submissions are validated by grz-tools when they arrive, so such a value
was valid against the schema version in force at the time; the database simply
spans several versions. The `declared in schema` column records it as
`no - predates this version` and nothing is highlighted. It is still worth a
glance for one reason: if a whole workbook is full of them, the wrong schema file
was passed.

Every sheet ends with a `declared but never used (8 of 10)` line naming them, the
**index** sheet carries a per-field count, and the same summary goes to the
console:

```
checked 20 enum(s) against grz-schema.json: 75 declared value(s) never used
  labData.libraryType: panel, panel_lr, wes_lr, wgs, wgs_lr, wxs_lr, other, unknown
  labData.sequencingLayout: single-end, reverse, other
```

Pass the schema the submissions were actually **validated against** — that is
`GRZ/grz-schema.json` on `main`, not the schema proposal. The job here is to
measure the vocabulary in force; measuring against the proposal is what `--vocab`
does. `--schema` and `--vocab` can be given together and answer different halves
of the question: which existing values are dead, and which proposed values are
missing.

The workbook contains:

- **summary** — submissions seen per GRZ, and a warning if script versions differ
- **index** — every surveyed field, with how many distinct values were used and —
  with `--schema` — how many values the schema declares and how many of those
  were never used
- **one sheet per field** — values down the rows, GRZs across the columns, plus
  totals and share of all observations

Where `--vocab` was given, each value is marked as in or out of the proposed
vocabulary, unmatched rows are highlighted, and the sheet ends with an overall
coverage figure such as `7/12 observations (58.3%)`. That figure is the point of
the exercise: it says whether a candidate enum is usable as drafted, and the
highlighted rows are the list of values still to be mapped or added.

## What is surveyed

**Controlled vocabularies today** — `submissionType`, `coverageType`,
`diseaseType`, `genomicStudyType`, `genomicStudySubtype`, `gender`, `relation`,
`noScopeJustification`, `sampleConservation`, `sequenceType`, `sequenceSubtype`,
`fragmentationMethod`, `libraryType`, `enrichmentKitManufacturer`,
`sequencingLayout`, `tumorCellCount.method`, `referenceGenome`, `fileType`,
`readOrder`, `checksumType`.

**Free text today** — `tissueOntology.name` and `.version`, `tissueTypeId`,
`tissueTypeName`, `libraryPrepKit`, `libraryPrepKitManufacturer`,
`sequencerModel`, `sequencerManufacturer`, `kitName`, `kitManufacturer`,
`enrichmentKitDescription`, `labDataName`, `bioinformaticsPipelineName`,
`callerUsed.name`.

**Derived checks** that a plain value count cannot answer:

| Check | Question it answers |
|---|---|
| `tissueTypeId_is_BTO_format` | how many identifiers match `^BTO:[0-9]{7}$` |

## Adding a field

Both dictionaries near the top of `survey_grz_metadata.py` map a label to a
path through the metadata document, where `[]` descends into an array:

```python
"labData.sequencingLayout": "donors[]/labData[]/sequencingLayout",
```

Add an entry and it is counted. Bump `SCRIPT_VERSION` so that reports produced
before and after are distinguishable.
