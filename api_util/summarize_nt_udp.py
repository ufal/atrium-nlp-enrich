import sys
import os
import argparse
from pathlib import Path
import csv
import re
from xml.sax.saxutils import escape


# Increase CSV field size limit just in case
csv.field_size_limit(sys.maxsize)

# --- CNEC 2.0 Type Hierarchy Mapping ---
CNEC_TYPE_MAP = {
    "a": "Address/Number/Time (General)",
    "A": "Complex Address/Number/Time",
    "ah": "Street address",
    "at": "Phone/Fax number",
    "az": "Zip code",
    "g": "Geographical name (General)",
    "G": "Geographical name (General)",
    "g_": "Geographical name (General)",
    "gu": "Settlement name (City/Town)",
    "gl": "Nature/Landscape name (Mountain/River)",
    "gq": "Urban geographical name (Street/Square)",
    "gr": "Territorial name (State/Region)",
    "gs": "Super-terrestrial name (Star/Planet)",
    "gc": "States/Provinces/Regions",
    "gt": "Continents",
    "gh": "Hydronym (Bodies of water)",
    "i": "Institution name (General)",
    "i_": "Institution name (General)",
    "I": "Institution name (General)",
    "ia": "Conference/Contest",
    "if": "Company/Firm",
    "io": "Organization/Society",
    "ic": "Cult/Educational institution",
    "m": "Media name (General)",
    "mn": "Periodical name (Newspaper/Magazine)",
    "ms": "Radio/TV station",
    "mi": "Internet links",
    "o": "Artifact name (General)",
    "o_": "Artifact name (General)",
    "oa": "Cultural artifact (Book/Painting)",
    "oe": "Measure unit",
    "om": "Currency",
    "or": "Directives, norms",
    "op": "Product (General)",
    "p": "Personal name (General)",
    "p_": "Personal name (General)",
    "P": "Complex personal names",
    "pf": "First name",
    "ps": "Surname",
    "pm": "Second name",
    "ph": "Nickname/Pseudonym",
    "pc": "Inhabitant name",
    "pd": "Academic titles",
    "pp": "Relig./myth persons",
    "me": "Email address",
    "t": "Time expression (General)",
    "T": "Complex time expressions",
    "td": "Day",
    "th": "Hour",
    "tm": "Month",
    "ty": "Year",
    "tf": "Holiday/Feast",
    "tt": "Time block",
    "n": "Number expression (General)",
    "N": "Complex number expressions",
    "n_": "Number expression (General)",
    "na": "Age",
    "nb": "Volu-metric number",
    "nc": "Cardinal number",
    "ni": "Itemizer (1.)",
    "no": "Ordinal number",
    "ns": "Sport score",
    "unk": "Unknown Type",
    "O": "None",
    "C": "Complex bibliographic expression",
}



def write_teitok_from_conllu(conllu_path, teitok_path, doc_id=None):
    """
    Produce TEITOK-style TEI XML from a CoNLL-U file (flexiconv-compatible).
    Structure: <s xml:id="..."> containing <tok> elements per token with full UD
    attributes. Heads reference the token's unique xml:id rather than ordinal
    position. SpaceAfter=No in MISC collapses whitespace between tokens.
    NER tag from MISC is written as the 'ne' attribute.
    """
    from xml.sax.saxutils import escape

    # --- parse sentences from CoNLL-U ---
    sentences = []
    current_sent = []
    sent_id = None
    sent_text = None

    try:
        with open(conllu_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.rstrip('\n')
                stripped = line.strip()

                if stripped.startswith('# sent_id'):
                    sent_id = stripped.split('=', 1)[1].strip() if '=' in stripped else None
                    continue
                if stripped.startswith('# text'):
                    sent_text = stripped.split('=', 1)[1].strip() if '=' in stripped else None
                    continue
                if stripped.startswith('#') or not stripped:
                    if not stripped and current_sent:
                        sentences.append({'id': sent_id, 'text': sent_text, 'tokens': current_sent})
                        current_sent = []
                        sent_id = None
                        sent_text = None
                    continue

                cols = stripped.split('\t')
                # skip multiword / empty nodes
                if len(cols) < 10 or '-' in cols[0] or '.' in cols[0]:
                    continue

                misc = parse_misc(cols[9])
                tok = {
                    'id':       cols[0],
                    'form':     cols[1],
                    'lemma':    cols[2],
                    'upos':     cols[3],
                    'xpos':     cols[4],
                    'feats':    cols[5],
                    'head':     cols[6],
                    'deprel':   cols[7],
                    'deps':     cols[8],
                    'space_after': misc.get('SpaceAfter', 'Yes') != 'No',
                    'ner':      misc.get('NER', ''),
                }
                current_sent.append(tok)

        # flush last sentence if file doesn't end with blank line
        if current_sent:
            sentences.append({'id': sent_id, 'text': sent_text, 'tokens': current_sent})

    except Exception as e:
        print(f"  [Error] reading for TEITOK conversion {conllu_path}: {e}", file=sys.stderr)
        return False

    doc_id_safe = escape(doc_id or Path(teitok_path).stem)

    try:
        with open(teitok_path, 'w', encoding='utf-8') as out:
            out.write('<?xml version="1.0" encoding="utf-8"?>\n')
            out.write(
                f'<TEI xmlns="http://www.tei-c.org/ns/1.0" xml:lang="cs">\n'
                f'  <teiHeader/>\n'
                f'  <text>\n'
                f'    <body>\n'
                f'      <div type="document" xml:id="{doc_id_safe}">\n'
            )

            for s_idx, sent in enumerate(sentences, start=1):
                raw_sid = sent['id'] or f"{doc_id_safe}.s{s_idx}"
                # make the sentence id safe and scoped under doc
                sid = escape(raw_sid if raw_sid.startswith(doc_id_safe) else f"{doc_id_safe}.{raw_sid}")
                text_attr = f' text="{escape(sent["text"])}"' if sent.get('text') else ''
                out.write(f'        <s xml:id="{sid}"{text_attr}>\n')

                # build mapping ordinal → xml:id for head resolution
                tok_xmlid = {}
                for tok in sent['tokens']:
                    tok_xmlid[tok['id']] = f"{sid}.w{tok['id']}"

                for tok in sent['tokens']:
                    wid = escape(tok_xmlid[tok['id']])

                    # resolve head to unique xml:id (or '0' for root)
                    head_val = tok['head']
                    if head_val == '0':
                        head_ref = '0'
                    else:
                        head_ref = escape(tok_xmlid.get(head_val, head_val))

                    attrs = (
                        f' xml:id="{wid}"'
                        f' lemma="{escape(tok["lemma"])}"'
                        f' upos="{escape(tok["upos"])}"'
                        f' xpos="{escape(tok["xpos"])}"'
                    )
                    if tok['feats'] and tok['feats'] != '_':
                        attrs += f' feats="{escape(tok["feats"])}"'
                    attrs += f' head="{head_ref}" deprel="{escape(tok["deprel"])}"'
                    if tok['deps'] and tok['deps'] != '_':
                        attrs += f' deps="{escape(tok["deps"])}"'
                    if tok['ner'] and tok['ner'] not in ('O', '_', ''):
                        attrs += f' ne="{escape(tok["ner"])}"'
                    # SpaceAfter=No → join flag for downstream tools
                    if not tok['space_after']:
                        attrs += ' join="right"'

                    out.write(f'          <tok{attrs}>{escape(tok["form"])}</tok>\n')

                out.write('        </s>\n')

            out.write('      </div>\n    </body>\n  </text>\n</TEI>\n')
        return True

    except Exception as e:
        print(f"  [Error] writing TEITOK {teitok_path}: {e}", file=sys.stderr)
        return False

# === New helper: parse boolean-like env/arg values ===
def bool_from_str(s, default=False):
    if s is None:
        return default
    if isinstance(s, bool):
        return s
    s = str(s).strip().lower()
    return s in ('1', 'true', 'yes', 'y', 'on')


def process_pipeline(conllu_dir, tsv_root, output_root, save_conllu=True, save_csv=True, save_teitok=False):
    conllu_path_obj = Path(conllu_dir)
    tsv_root_obj = Path(tsv_root)
    output_root_obj = Path(output_root)

    if not conllu_path_obj.exists():
        print(f"Error: CoNLL-U dir not found: {conllu_dir}")
        sys.exit(1)

    conllu_files = sorted(list(conllu_path_obj.glob('*.conllu')))
    print(f"Found {len(conllu_files)} documents to process.")

    output_root_obj.mkdir(parents=True, exist_ok=True)

    for conllu_file in conllu_files:
        doc_name = conllu_file.stem

        # per-document output folder: <output_root>/<doc_name>/
        doc_out_dir = output_root_obj / doc_name
        doc_out_dir.mkdir(parents=True, exist_ok=True)

        doc_out_conllu = doc_out_dir / f"{doc_name}.conllu"
        doc_out_csv    = doc_out_dir / f"{doc_name}.csv"
        doc_out_teitok = doc_out_dir / f"{doc_name}.teitok.xml"

        required_paths = []
        if save_conllu:  required_paths.append(doc_out_conllu)
        if save_csv:     required_paths.append(doc_out_csv)
        if save_teitok:  required_paths.append(doc_out_teitok)

        if required_paths and all(p.exists() for p in required_paths):
            print(f"[Skip] {doc_name}: all requested outputs already exist.")
            continue

        doc_tsv_dir = tsv_root_obj / doc_name
        if not doc_tsv_dir.exists() or not doc_tsv_dir.is_dir():
            print(f"[Skip] No TSV directory found for: {doc_name} (checked {doc_tsv_dir})")
            continue

        print(f"[Processing] {doc_name}...")

        tsv_data = get_sorted_tsv_content(doc_tsv_dir)
        if not tsv_data:
            print(f"  [Warn] No valid TSV data found in {doc_tsv_dir}")
            continue

        merged_written = merge_and_write(conllu_file, tsv_data, doc_out_conllu)
        if not merged_written:
            print(f"  [Error] failed to create merged conllu for {doc_name}, skipping.")
            continue

        if save_csv:
            process_merged_file(doc_out_conllu, doc_out_csv)

        if save_teitok:
            write_teitok_from_conllu(doc_out_conllu, doc_out_teitok, doc_id=doc_name)

        if not save_conllu:
            try:
                if doc_out_conllu.exists():
                    doc_out_conllu.unlink()
            except Exception as e:
                print(f"  [Warn] unable to remove intermediate conllu {doc_out_conllu}: {e}", file=sys.stderr)

    print("\nPipeline Complete.")




def load_config(config_path="api_config.env"):
    if not os.path.exists(config_path):
        return
    with open(config_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', '_', name)


def get_ne_explanation(raw_tag):
    if raw_tag == "O" or not raw_tag or raw_tag == "_":
        return ""

    if raw_tag.startswith("B-") or raw_tag.startswith("I-"):
        primary = raw_tag.split('|')[0]
        short_code = primary[2:]
        return CNEC_TYPE_MAP.get(short_code, f"Unknown Code ({short_code})")

    return ""


def get_sorted_tsv_content(doc_tsv_dir):
    """
    Reads all .tsv files in the document directory, sorts them by page number
    (assuming format doc-PAGE.tsv), and returns a single list of tokens/tags.
    """
    all_data = []

    files = list(Path(doc_tsv_dir).glob("*.tsv"))

    def sort_key(filepath):
        try:
            match = re.search(r'-(\d+)\.tsv$', filepath.name)
            if match:
                return int(match.group(1))
            return 0
        except:
            return 0

    files.sort(key=sort_key)

    for fpath in files:
        with open(fpath, 'r', encoding='utf-8') as f:
            header = next(f, None)
            for line in f:
                line = line.strip()
                if not line: continue

                parts = line.split('\t')
                if len(parts) >= 2:
                    all_data.append({'token': parts[0], 'tag': parts[1]})
                else:
                    all_data.append({'token': parts[0], 'tag': 'O'})

    return all_data


def merge_and_write(conllu_path, tsv_data, output_path):
    tsv_index = 0
    tsv_len = len(tsv_data)

    try:
        with open(conllu_path, 'r', encoding='utf-8') as f_conllu, \
                open(output_path, 'w', encoding='utf-8') as f_out:

            for line in f_conllu:
                stripped_line = line.strip()

                if not stripped_line or stripped_line.startswith('#'):
                    f_out.write(line)
                    continue

                cols = stripped_line.split('\t')

                if len(cols) >= 2 and '-' not in cols[0] and '.' not in cols[0]:
                    if tsv_index < tsv_len:
                        tsv_item = tsv_data[tsv_index]
                        new_attr = f"NER={tsv_item['tag']}"

                        if len(cols) > 9:
                            if cols[9] == '_':
                                cols[9] = new_attr
                            else:
                                cols[9] += f"|{new_attr}"
                        else:
                            while len(cols) < 9:
                                cols.append('_')
                            cols.append(new_attr)

                        f_out.write('\t'.join(cols) + '\n')
                        tsv_index += 1
                    else:
                        f_out.write(line)
                else:
                    f_out.write(line)

        return True

    except Exception as e:
        print(f"Error merging {conllu_path}: {e}", file=sys.stderr)
        return False


def parse_features(feat_str):
    if feat_str == '_' or not feat_str: return {}
    return {k: v for item in feat_str.split('|') if '=' in item for k, v in [item.split('=', 1)]}


def parse_misc(misc_str):
    if misc_str == '_' or not misc_str: return {}
    misc = {}
    for item in misc_str.split('|'):
        if '=' in item:
            k, v = item.split('=', 1)
            misc[k] = v
        else:
            misc[item] = "Yes"
    return misc


def write_document_csv(rows, out_path):
    if not rows: return

    feature_keys = set()
    misc_keys = set()
    for r in rows:
        for k in r.keys():
            if k.startswith('udpipe.feats.'):
                feature_keys.add(k)
            elif k.startswith('udpipe.misc.'):
                misc_keys.add(k)

    header = ['page_id', 'token', 'lemma', 'position', 'nameTag', 'NE'] + \
             sorted(list(feature_keys)) + sorted(list(misc_keys))

    try:
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            # Added aggressive quoting to ensure proper formatting of stray hyphens etc.
            writer = csv.DictWriter(f, fieldnames=header, quoting=csv.QUOTE_ALL, quotechar='"')
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        print(f"  [Error] writing {out_path}: {e}", file=sys.stderr)


def process_merged_file(merged_filepath, output_csv_path):
    all_rows = []
    page_counter = 0

    with open(merged_filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            if line.startswith('# sent_id'):
                parts = line.split('=', 1)
                if len(parts) > 1 and parts[1].strip() == '1':
                    page_counter += 1

            if line.startswith('#') or not line:
                continue

            parts = line.split('\t')
            if len(parts) < 10 or '-' in parts[0]:
                continue

            if page_counter == 0: page_counter = 1

            misc = parse_misc(parts[9])
            feats = parse_features(parts[5])

            ner_tag = misc.get('NER', '')
            # ignore O tags and record them as empty cells
            # if ner_tag == 'O':
            #     ner_tag = ''

            row = {
                'page_id': page_counter,
                'token': parts[1],
                'lemma': parts[2],
                'position': parts[0],
                'nameTag': ner_tag,
                'NE': get_ne_explanation(ner_tag)
            }

            for k, v in feats.items(): row[f'udpipe.feats.{k}'] = v
            for k, v in misc.items():
                if k != 'NER': row[f'udpipe.misc.{k}'] = v

            all_rows.append(row)

    if all_rows:
        write_document_csv(all_rows, output_csv_path)







def main():
    load_config('api_config.env')
    parser = argparse.ArgumentParser()
    parser.add_argument('--conllu-dir', default=os.getenv('CONLLU_INPUT_DIR'))
    parser.add_argument('--tsv-dir', default=os.getenv('TSV_INPUT_DIR'))
    parser.add_argument('--out-dir', default=os.getenv('SUMMARY_OUTPUT_DIR'))

    # format flags: can be provided on CLI or via environment variables (SAVE_CONLLU_NE, SAVE_CSV, SAVE_TEITOK)
    parser.add_argument('--save-conllu-ne', default=os.getenv('SAVE_CONLLU_NE', '1'),
                        help="1/0 whether to keep the merged CoNLL-U per document (env: SAVE_CONLLU_NE).")
    parser.add_argument('--save-csv', default=os.getenv('SAVE_CSV', '1'),
                        help="1/0 whether to write the summary CSV per document (env: SAVE_CSV).")
    parser.add_argument('--save-teitok', default=os.getenv('SAVE_TEITOK', '0'),
                        help="1/0 whether to write TEITOK-XML per document (env: SAVE_TEITOK).")

    args = parser.parse_args()

    if not all([args.conllu_dir, args.tsv_dir, args.out_dir]):
        print("Missing arguments. Check config or flags.")
        sys.exit(1)

    save_conllu = bool_from_str(args.save_conllu_ne, default=True)
    save_csv = bool_from_str(args.save_csv, default=True)
    save_teitok = bool_from_str(args.save_teitok, default=False)

    process_pipeline(args.conllu_dir, args.tsv_dir, args.out_dir,
                     save_conllu=save_conllu, save_csv=save_csv, save_teitok=save_teitok)



if __name__ == "__main__":
    main()