# Checking a real collection with flexiconv (issue #10)

For anyone about to use the [flexiconv path](../usage.md#other-input-formats-flexiconv) on a new collection: how to
check what the conversion keeps, document by document, and what a reference run on flexiconv's own examples gave.
It measures the conversion (rows, tokens, boxes, the TEITOK-core rules), not the quality of the annotation.

## The procedure

Before relying on the flexiconv path for a collection, convert a few real documents of each kind and record what
comes out. `api_util/flexiconv_report.py` prints the table for you, one row per converted file, and lists the inputs
that produced nothing:

```bash
bash api_flexiconv.sh
python3 api_util/flexiconv_report.py "$TEITOK_FLEXICONV_DIR" --inputs "$INPUT_DOCS_DIR"
# | Input | Pages | Rows | Tokens | Elements with bbox | `--profile core` |
# | hocr `page_1.hocr` | 1 | 3 | 13 | 15 | ✅ |   ... exit 0 only if every file passes
```

Fill in the notes by looking at a few of the files:

| Input (format, source)      | Converted? | `--profile core` | Rows | Notes (layout kept? text order? encoding?) |
|-----------------------------|------------|------------------|------|--------------------------------------------|
| PAGE XML (e.g. Transkribus) |            |                  |      |                                            |
| hOCR (e.g. Tesseract)       |            |                  |      |                                            |
| docx / odt                  |            |                  |      |                                            |
| pdf (text layer)            |            |                  |      |                                            |
| txt / md                    |            |                  |      |                                            |

## Reference run (2026-09-23)

flexiconv v0.3.10, its own `examples/` plus one Czech txt, all through `api_flexiconv.sh`, all passing
`--profile core`, nothing installed during the run:

| Input                              | Rows | Tokens | Elements with bbox |
|------------------------------------|------|--------|--------------------|
| PAGE XML `aletheiaexamplepage.xml` | 96   | 532    | 593                |
| hOCR `output_page_1.hocr`          | 3    | 13     | 15                 |
| ALTO `sample.alto.xml`             | 1    | 5      | 8                  |
| docx `16453-1.docx`                | 21   | 464    | —                  |
| md `FORMATS_AND_MAPPINGS.md`       | 209  | 1463   | —                  |
| txt (2 paragraphs)                 | 2    | 10     | —                  |

Before the 2026-09 reader fallback every one of them read as **0 rows**. For docx/odt/epub, flexiconv also writes
the embedded images into a `<output>_files/` directory next to the TEITOK file.

Real flexiconv v0.3.10 output for txt, md, PAGE XML, hOCR and ALTO is committed in
[tests/fixtures/teitok/flexiconv/](../../tests/fixtures/teitok/flexiconv) and covered by the tests.
