# 🤝 Contributing to the NLP Enrichment Pipeline of the ATRIUM project

Thank you for your interest in contributing!
This document describes the development workflow, conventions, and rules for contributors.


## Branches & Environments

| Branch   | Environment          | Rule                                                                            |
|----------|----------------------|---------------------------------------------------------------------------------|
| `test`   | Staging              | Base for all development. Always branch from `test`.                            |
| `master` | Stable / Integration | Merged exclusively by a human reviewer. Do not open PRs directly into `master`. |

```text
test  ←  feature/<issue>
test  ←  bugfix/<issue>
master   ←  (humans only, after test stabilises)
```

---

## Branch Naming

| Type             | Pattern                       | Example                       |
|------------------|-------------------------------|-------------------------------|
| New feature      | `feature/<issue>`             | `feature/42-teitok-export`    |
| Bug fix          | `bugfix/<issue>`              | `bugfix/17-chunk-merge-error` |
| Hotfix on master | `hotfix/<issue>`              | `hotfix/99-api-timeout`       |

---

## Contributor Workflow

1. **Create an issue** (or find an existing one) describing the problem or feature.
2. **Branch from `master`:**

   ```bash
   git checkout master
   git pull origin master
   git checkout -b feature/<issue-number>
   ```

3. **Run the minimum tests** (see the Testing section).
4. **Open a Pull Request** targeting the `test` branch.

---

## Pull Request Format

Every PR must include:

- **Issue link:** `Closes #<number>` or `Refs #<number>`
- **Motivation:** why the change is needed
- **Description of change:** what was changed and how
- **Testing:** what was run, what passed, what could not be executed

Use a **Draft PR** if the work is not ready for review.

**Do not open PRs into `master`** — merging into `master` is exclusively the maintainers' 
responsibility.

---

## Commit Messages

Format:

```
[type] concise description (#issue-number)
```

Allowed types:

| Type       | When to use                           |
|------------|---------------------------------------|
| `add`      | Added content (general)               |
| `edit`     | Edited existing content (general)     |
| `remove`   | Removed existing content (general)    |
| `fix`      | Bug fix                               |
| `refactor` | Refactoring without behaviour change  |
| `test`     | Adding or updating tests              |
| `docs`     | Documentation only                    |
| `chore`    | Build, dependencies, CI configuration |
| `style`    | Formatting, no logic change           |
| `perf`     | Performance optimisation              |

Examples:

```
[feat] Add per-document TEITOK XML export (#42)
[fix] Correct chunk boundary detection in chunk.py (#17)
[docs] Update config_api.txt parameter descriptions (#0)
```

---

## Testing

### Minimum before every commit

```bash
# 1. Python compilation check
python -m compileall -q api_util/

# 2. Pre-commit hooks
pre-commit run --all-files
```

### Scope-based testing

```bash
# Run targeted unit tests
python -m pytest api_util/
```

Use the data samples in `data_samples/` as input when smoke-testing the pipeline.

---

## Generated Artefacts

Some files are modified automatically by scripts or hooks:

| Script              | What it generates                                     |
|---------------------|-------------------------------------------------------|
| `api_1_manifest.sh` | `manifest.tsv` — ordered list of all pages to process |
| `api_2_udp.sh`      | `UDP/*.conllu` — per-document CoNLL-U files           |
| `api_3_nt.sh`       | `NE/*/*.tsv` — per-page NER-annotated TSV files       |
| `api_4_stats.sh`    | `UDP_NE/`, `TEITOK/`, `summary_ne_counts.csv`         |

Rules:

1. Do not manually edit auto-generated output files.
2. After changing chunking logic, re-run `api_2_udp.sh` to verify CoNLL-U validity.
3. After changing NER merging logic or TEITOK XMLs composition, re-run `api_4_stats.sh` 
and inspect `summary_ne_counts.csv`.

---

## Output Format Flags

Pipeline output is controlled by boolean flags in `config_api.txt`. When adding a new output format, 
follow this pattern:

| Variable         | Description                                              | Default |
|------------------|----------------------------------------------------------|---------|
| `SAVE_CONLLU_NE` | Enriched CoNLL-U with NER in the `MISC` field            | `true`  |
| `SAVE_CSV`       | Token-level summary CSV per document                     | `true`  |
| `SAVE_TEITOK`    | TEITOK-style TEI XML with bounding boxes (requires ALTO) | `true`  |

New flags must be documented here and in `config_api.txt`.

---

## Repository Documentation Management

Each documentation file has one target audience and one responsibility.
Rules are not repeated — cross-references are used instead.

| File              | Audience        | Responsibility                                 |
|-------------------|-----------------|------------------------------------------------|
| `README.md`       | GitHub visitors | Project overview, workflow stages, quick start |
| `CONTRIBUTING.md` | Developers      | Code conventions, branches, PRs, testing       |

Rules:

1. **Do not duplicate rules** — if a rule is defined in `CONTRIBUTING.md`, other files reference it rather than copying it.
2. **Single canonical source** — for each type of information, exactly one canonical file exists (see table above).
3. **When changing a rule**, update the canonical source and verify that referencing files still point correctly.

---

## 📞 Contacts & Acknowledgements

For technical questions contact **lutsai.k@gmail.com** 

**Issues:** https://github.com/ufal/atrium-nlp-enrich/issues


* **Developed by:** UFAL [^7]
* **Funded by:** ATRIUM [^4]
* **Models:** 
  * NameTag 3 [^6] 
  * UDPipe 2 [^5]
  
**©️ 2026 UFAL & ATRIUM**


[^2]: https://github.com/ufal/atrium-alto-postprocess
[^3]: https://ufal.mff.cuni.cz/~strakova/cnec2.0/ne-type-hierarchy.pdf
[^4]: https://atrium-research.eu/
[^5]: https://lindat.mff.cuni.cz/services/udpipe/api-reference.php
[^6]: https://lindat.mff.cuni.cz/services/nametag/api-reference.php
[^1]: https://github.com/ufal/atrium-nlp-enrich
[^7]: https://ufal.mff.cuni.cz/home-page

