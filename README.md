# grz_query_metadata

Survey which metadata values are actually used across GRZ submissions, so that
proposed changes to the [GRZ metadata schema](https://github.com/BfArM-MVH/MVGenomseq_GRZ)
can be decided on evidence rather than assumption.

Each GRZ runs `survey_grz_metadata.py` against its own submission database and
returns a small JSON report. Those reports are combined with
`aggregate_grz_surveys.py` into a single spreadsheet.

Typical questions this answers:

- How often is `wes` used instead of its synonym `wxs`? Is either safe to drop?
- How many submissions use an ontology other than BRENDA in `tissueOntology`?
- Is `reverse` in `sequencingLayout` ever used at all?
- How many donors would a proposed "a VCF must accompany raw reads" rule reject?
- Do the free-text `libraryPrepKit` and `sequencerModel` values map onto a
  proposed controlled vocabulary, and what share would fail?

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
python survey_grz_metadata.py \
    --db-url /path/to/submission.db.sqlite \
    --grz-id GRZK00123

# PostgreSQL
python survey_grz_metadata.py \
    --db-url postgresql://user@host/grzdb \
    --grz-id GRZK00123

# or take the URL from your grz config file
python survey_grz_metadata.py \
    --config-file /etc/grz/config.yaml \
    --grz-id GRZK00123
```

This writes `grz-survey-<grz-id>-<date>.json` in the working directory.

Useful flags:

| Flag | Effect |
|---|---|
| `--redact-freetext` | report counts only for free-text fields, not their values |
| `--out FILE` | write somewhere other than the default filename |
| `--max-freetext-values N` | cap distinct values reported per field (default 500) |

**Please run the tagged release** rather than the tip of the branch, so every
GRZ reports with the same script. The aggregation step flags it if reports were
produced by different versions.

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

The workbook contains:

- **summary** — submissions seen per GRZ, and a warning if script versions differ
- **index** — every surveyed field, with its distinct-value and observation counts
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
| `donor_raw_reads_has_vcf` | how many donors with BAM/FASTQ have no VCF |
| `tissueTypeId_is_BTO_format` | how many identifiers match `^BTO:[0-9]{7}$` |
| `donors_per_submission` | are there submissions with more than three donors |
| `donorCount_matches_genomicStudyType` | does the declared study type match the donor count |
| `index_donors_per_submission` | are there submissions with no index, or several |
| `readLength_present_on_bam_fastq` | is the existing conditional rule actually satisfied |
| `bed_files_per_submission` | is the documented "only one BED" rule respected |
| `duplicate_filePaths_in_submission` | is the same file declared more than once |
| `labData_with_empty_files_list` | how often is `files` present but empty |

## Adding a field

Both dictionaries near the top of `survey_grz_metadata.py` map a label to a
path through the metadata document, where `[]` descends into an array:

```python
"labData.sequencingLayout": "donors[]/labData[]/sequencingLayout",
```

Add an entry and it is counted. Bump `SCRIPT_VERSION` so that reports produced
before and after are distinguishable.
