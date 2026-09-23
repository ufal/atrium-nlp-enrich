# `schemas/teitok/` — Pinned TEITOK output contract (issue #28)

This directory vendors the XSD schema that `.teitok.xml` files must satisfy
before the pipeline packages them for the LINDAT dataset release.

## Files

| File         | Purpose                                                                                                            |
|--------------|--------------------------------------------------------------------------------------------------------------------|
| `teitok.xsd` | The output contract itself.                                                                                        |
| `xml.xsd`    | Local, trimmed copy of the W3C `xml.xsd`, providing `xml:lang`. Vendored so validation never needs network access. |

## What the writer emits ("TEITOK format 2")

`api_util/teitok_alto.py::write_teitok_merged()` stamps every document with
`<application ident="atrium-nlp-enrich" version="teitok-2">`. Since 2026-09 it follows the
conventions of the TEITOK tools themselves (flexiconv, flexipipe, teitok-tools,
xmltokenizer), not just a shape of its own:

| Aspect      | Format 2                                                                                                                                                                                                                                  |
|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Root        | `<TEI xmlnsoff="http://www.tei-c.org/ns/1.0" lang="cs">`. `lang` comes from ALTO `LANG` (majority), else the UDPipe model name, else it is omitted. It is mirrored in `profileDesc/langUsage/language@ident`.                              |
| Spacing     | Text-faithful. Tokens are inline in `<s>`, whitespace between `</tok>` and the next `<tok>` is a space and none is `SpaceAfter=No`. This also holds across `<lb/>` and `</name>` (an entity's trailing space sits inside `</name>`). `join="right"` is kept as the TEI-P5 marker. |
| Tokens      | `<tok id type ord lemma upos xpos feats head deprel join bbox>`. `@head` is the head word's `@id`; `@ord` is the CoNLL-U ID.                                                                                                              |
| MWT         | `<tok id bbox>abych<dtok id form ord lemma …/><dtok …/></tok>`. The surface token carries the text and bbox; `<dtok>` carries the words.                                                                                                   |
| Ids         | `w-N` (document-global), `w-N.K` (dtok), `s-N`, `n-N` (name), `facs-P` (surface), `pb-P`, `lb-P.L`, `b-P.K` (div), `fig-P.K`. The atrium_document record's `entities[].teitok_ref` and `pages[].teitok_surface` are these local ids.           |
| Entities    | `<name id type sameAs>`. `@type` is PER/ORG/LOC/MISC (`api_util/ner_types.py`), and the raw label goes in `@cnec`, `@onto`, `@archaeo` or `@label`.                                                                                       |
| Layout      | `<div type="TextBlock" [subtype=<ALTO TAGREFS label>] [lang]>`, or `type="text"` without ALTO. `<pb corresp="#facs-P">`, `<figure>`.                                                                                                      |
| Coordinates | `bbox="x1 y1 x2 y2"`: non-negative page-image pixels, origin at the page's top-left corner (`BBOX_ORIGIN=page`, the TEITOK norm). `BBOX_ORIGIN=printspace` measures from the ALTO PrintSpace instead. `<surface lrx lry>` is always the extent the boxes are measured in. |
| Header      | `notesStmt/note[@n="orgfile"]`; `revisionDesc/change@type` = `converted`, `tagged` + `subtype="parsed"`, `ner` (the phases TEITOK/flexicorp detect).                                                                                       |

Format-1 documents (before 2026-09: TEI namespace, `CTX.s1.w1` ids, `MarginTextZone-P`,
one `<tok>` per line) still validate — `tests/fixtures/teitok/legacy/CTX_format1.teitok.xml`
keeps it that way — except for negative bbox coordinates, which the old PrintSpace shift
could produce. Set `REGENERATE_TEITOK=true` once to rewrite them.

## Provenance

`teitok.xsd` is **not** copied from teitok.org or any upstream release: no TEITOK tool
ships an XSD, RNG or DTD. It describes exactly the subset of TEI this writer emits:

- **Source of truth:** `api_util/teitok_alto.py::write_teitok_merged()`, the
  writer behind the `stats` stage and every document in `data_samples/TEITOK/`.
- **Method:** hand-authored to encode the element/attribute shapes that writer
  produces, on both its code paths (with a source ALTO file, i.e. bbox-annotated
  and `<facsimile>`-bearing; and the text-only fallback without one).
- **Verified by:** `tests/test_validate_teitok.py::TestRealWriterRoundTrip`,
  which *runs* the writer and validates its output, and
  `test_committed_samples_are_what_the_writer_produces_today`, which regenerates
  `data_samples/TEITOK/` and compares. The curated fixtures in
  `tests/fixtures/teitok/` are real writer output too. See "How this schema went wrong once".
- **`xml.xsd`:** trimmed subset of `https://www.w3.org/2001/xml.xsd`,
  retaining only `xml:lang` (plus `xml:space`, `xml:base`, `xml:id` for
  forward compatibility), vendored for network-free validation per issue
  #28's schema-management decision.

## Upstream conformance

A schema derived from the writer can only say that the output kept its shape. It said
nothing about whether the output meant the same to TEITOK: format 1 validated while
every upstream reader saw a space after every token. Conformance is therefore tested
separately, by reading the output the way the tools do:

- `tests/test_teitok_conformance.py` (stdlib, always runs) reconstructs the CoNLL-U from
  the XML the way flexiconv's `load_teitok` and flexipipe do: space = a space character in
  `tok.tail`, words from `<dtok>`, heads through `@id`. It then compares sentence texts,
  every `SpaceAfter`, MWT, heads, ids and entity attributes with the input.
- The same file's last test repeats the round-trip through the pinned flexiconv
  (`requirements_flexiconv.txt`, v0.3.10) when it is installed. The `teitok-schema`
  workflow installs it for that step.
- `api_util/validate_teitok_xml.py --profile core` checks rules that hold for *any*
  TEITOK document: `<TEI>` root, `<text>`, unique `@id`, resolvable `@head`, no whitespace
  after a `join="right"` token, and non-negative bboxes.

Upstream references used: flexiconv `v0.3.10` (`a982b88`), flexipipe `73188c5`,
xmltokenizer `4b05623`, flexicorp `61f6543`, teitok-tools `2968265`.

## No target namespace — deliberate

`teitok.xsd` declares **no `targetNamespace`**. That is not an oversight.

`write_teitok_merged()` opens every document with:

```xml
<TEI xmlnsoff="http://www.tei-c.org/ns/1.0" lang="cs">
```

`xmlnsoff`, not `xmlns`; `lang`, not `xml:lang`. This is TEITOK's own
convention for keeping documents *out* of the TEI namespace so its tooling can
address elements unprefixed, and it has been the writer's output since
`api_util/teitok_alto.py` was added. So in real documents `xmlnsoff` and `lang`
are ordinary attributes — both are declared on `<TEI>` in the schema, because an
undeclared attribute is itself a validation error.

Documents that *do* carry the real TEI namespace also exist: format-1 exports, and
anything through `POST /rescale` that came in namespaced, since `service/rescale.py` is a
regex transform that preserves whatever namespace its input declared.
`api_util/validate_teitok_xml.py::_strip_tei_namespace` strips the TEI namespace before
validating, so one schema covers both conventions without duplicating it.

### Caveat: `xmllint` is only a partial cross-check

Because the namespace normalization lives in the Python validator, a bare

```bash
xmllint --noout --schema schemas/teitok/teitok.xsd <file>
```

agrees with the gate only for **no-namespace** documents — i.e. anything the
writer produces, including `data_samples/TEITOK/*`. Point it at a namespaced document
(`tests/fixtures/teitok/legacy/`) and it reports `No matching global declaration
available for the validation root`, which is an artefact of the missing normalization
step, *not* a real violation. Use `python3 api_util/validate_teitok_xml.py <dir>` as the
authority.

## Which emitters are gated, and how

Three code paths in this repo write `*.teitok.xml`. They are covered to
different depths, on purpose:

| Emitter         | Entry point                                                                               | Gate                                                                                      |
|-----------------|-------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| `stats` stage   | `api_4_stats.sh` → `api_util/summarize_nt_udp.py` → `teitok_alto.py::write_teitok_merged` | **Full XSD** over `$TEITOK_OUTPUT_DIR` minus `$TEITOK_FLEXICONV_DIR`, hard fail before `atrium_paradata.py finish` |
| flexiconv       | `api_flexiconv.sh` → `api_util/flexiconv_convert.py`                                      | **TEITOK-core** (`--profile core`) over `$TEITOK_FLEXICONV_DIR`, hard fail               |
| `POST /rescale` | `service/api.py` → `service/rescale.py`                                                   | **Advisory**: `schema_valid` / `schema_errors` in the response                            |

flexiconv output comes from a third-party converter across the `FLEXICONV_FORMATS`
of `config_api.txt`. It is a *different* TEITOK profile: no `<s>`; `<p>` text for
txt/md/docx/pdf/html; `<tok bbox>` + `<lb/>` for PAGE XML/hOCR/ALTO; split punctuation
without `@id`. This schema would reject it for not being this writer's output rather
than for being broken. So it goes to its own `$TEITOK_FLEXICONV_DIR` (default
`$TEITOK_OUTPUT_DIR/flexiconv`), which `api_4_stats.sh` excludes (`--exclude`), and it is
checked with the core profile. Real flexiconv v0.3.10 output is committed as fixtures in
`tests/fixtures/teitok/flexiconv/`.

`/rescale` reports rather than enforces because the endpoint faithfully
transforms whatever it is handed, including legacy documents that predate this
schema; failing them would break a working tool. `schema_valid` is `null` when
no verdict could be reached, so callers can tell "not conformant" from
"not checked".

## Keeping this schema current

If `teitok_alto.py`'s writer changes (new attributes, new element types, new
fallback branches), `teitok.xsd` must be updated in the same PR — this schema
describes the writer's actual contract, not an aspirational one.
`TestRealWriterRoundTrip` will fail first and point at the drift. Never fix such
a failure by loosening the schema without checking the writer diff: a genuinely
new element belongs in the schema, a *renamed* one is usually a bug. A change readers
can notice also bumps `WRITER_FORMAT` in `teitok_alto.py`.

After a writer change, regenerate the committed examples and the curated fixtures:

```bash
python3 - <<'EOF'
import sys; sys.path[:0] = [".", "api_util"]
from api_util.teitok_alto import write_teitok_merged
for d in ("CTX000000001", "CTX000000002", "CTX000000003"):
    write_teitok_merged(f"data_samples/UDP_NE/{d}/{d}.conllu", f"data_samples/TEITOK/{d}.teitok.xml",
                        f"data_samples/ALTO/{d}.alto.xml", doc_id=d,
                        model_nametag="nametag3-czech-cnec2.0-240830")  # as their paradata records
EOF
```

Fixtures live in `tests/fixtures/teitok/` — **not** in `data_samples/TEITOK/`,
which is the default `TEITOK_OUTPUT_DIR` (`config_api.txt`). Keeping the
deliberately-invalid `CTX_invalid.teitok.xml` out of that directory is what
stops a default-config run from failing its own gate on a fixture.
`data_samples/TEITOK/` holds real example output only.

## How this schema went wrong once

Worth recording, because the failure mode is easy to repeat. The first version
of this gate shipped with a `targetNamespace` of `http://www.tei-c.org/ns/1.0`
and `elementFormDefault="qualified"`, and with three fixtures hand-authored
using `xmlns=`. Every fixture test passed. The gate nevertheless rejected
**100% of real pipeline output**, because the writer emits `xmlnsoff` — so
`api_4_stats.sh` would have halted on every run that produced TEITOK, and
`POST /enrich` would have failed every request.

Hand-authored fixtures validated against a hand-authored schema confirm each
other and nothing else. The fix that matters is not the namespace edit; it is
`TestRealWriterRoundTrip`, which makes the real writer the arbiter. The same lesson
applied one level up in 2026-09: a writer-derived schema confirms the writer and nothing
else, which is why upstream conformance now has its own test lane.

## Future direction

Resolution-independent (relative, 0–1) bounding boxes were proposed to the TEITOK
maintainers (ufal/flexiconv#1); there has been no reply, and every TEITOK tool writes
absolute page-image pixels. If relative coordinates are ever adopted upstream,
`bboxType` will need to accept them alongside or instead of the current
`"x1 y1 x2 y2"` integer pattern.
