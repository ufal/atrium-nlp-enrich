import sys
import os
import argparse
from pathlib import Path
import csv
import re
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

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


# Replace the bare escape() calls on attribute values with this helper:
def _attr(value: str) -> str:
    """Escape a string for use inside an XML attribute value (double-quoted)."""
    return escape(value, {'"': '&quot;'})


def _parse_alto(alto_path):
    """
    Parse ALTO XML (v2/v3/v4/no-namespace).

    Returns:
        alto_strings : list of dicts in document order
                       {'content', 'left', 'top', 'right', 'bottom'}
                       HypPart2 entries are kept so their characters are
                       visible to the aligner; HypPart1 hyphen is kept too
                       (the NLP tokeniser emits it as a separate '-' token).
        alto_pages   : list of {'id', 'width', 'height'}
    """
    alto_strings = []
    alto_pages   = []

    if not (alto_path and Path(alto_path).exists()):
        return alto_strings, alto_pages

    try:
        tree = ET.parse(alto_path)
        root = tree.getroot()

        ns_uri = ''
        if root.tag.startswith('{'):
            ns_uri = root.tag[1:root.tag.index('}')]

        def _tag(local):
            return f'{{{ns_uri}}}{local}' if ns_uri else local

        for page in root.iter(_tag('Page')):
            alto_pages.append({
                'id':     page.get('ID', ''),
                'width':  page.get('WIDTH', ''),
                'height': page.get('HEIGHT', ''),
            })

        for string in root.iter(_tag('String')):
            content = string.get('CONTENT', '')
            if not content:
                continue
            try:
                hpos   = float(string.get('HPOS',   0))
                vpos   = float(string.get('VPOS',   0))
                width  = float(string.get('WIDTH',  0))
                height = float(string.get('HEIGHT', 0))
                alto_strings.append({
                    'content': content,
                    'left':    int(hpos),
                    'top':     int(vpos),
                    'right':   int(hpos + width),
                    'bottom':  int(vpos + height),
                })
            except (ValueError, TypeError):
                pass

    except Exception as e:
        print(f'  [Warn] Failed to parse ALTO {alto_path}: {e}', file=sys.stderr)

    return alto_strings, alto_pages


def _align_tokens_to_alto(tokens, alto_strings):
    """
    Align a flat list of token dicts to ALTO String bounding boxes using
    greedy, left-to-right, character-level matching.

    Both sides are NFC-normalized before comparison to guard against
    NFC/NFD mismatches between ABBYY ALTO output and UDPipe token forms
    (confirmed: NFD token vs NFC ALTO → silent None without normalization).

    On mismatch, the aligner skips up to MAX_SKIP characters forward in
    the ALTO stream before giving up on a token. Without this, a single
    OCR divergence (e.g. "Červinky" vs "Červinka") leaves `pos` stuck
    and causes every subsequent token to also fail (cascade confirmed).
    """
    if not alto_strings:
        return [None] * len(tokens)

    MAX_SKIP = 50  # max chars to advance on mismatch before giving up

    # Flatten ALTO strings into a single NFC character sequence.
    # Each entry: (char, alto_string_index)
    # A virtual space (-1) is inserted between strings to allow skipping gaps.
    import unicodedata
    char_seq = []
    for idx, s in enumerate(alto_strings):
        content = unicodedata.normalize('NFC', s['content'])
        for ch in content:
            char_seq.append((ch, idx))
        char_seq.append((' ', -1))

    bboxes = [None] * len(tokens)
    pos    = 0

    for tok_idx, tok in enumerate(tokens):
        form = unicodedata.normalize('NFC', tok.get('form', ''))
        if not form:
            continue

        # Try matching from pos, then pos+1 … pos+MAX_SKIP.
        # This lets the aligner resync after an OCR/tokeniser divergence
        # without cascading failures into subsequent tokens.
        for skip in range(MAX_SKIP + 1):
            start = pos + skip
            # Advance past inter-string gaps at the scan start
            while start < len(char_seq) and char_seq[start][1] == -1:
                start += 1
            if start >= len(char_seq):
                break

            j = start
            first_alto_idx = None
            match_ok = True

            for fch in form:
                # Skip inter-string gaps inside a token match
                while j < len(char_seq) and char_seq[j][1] == -1:
                    j += 1
                if j >= len(char_seq):
                    match_ok = False
                    break
                seq_ch, seq_alto_idx = char_seq[j]
                if seq_ch == fch:
                    if first_alto_idx is None and seq_alto_idx >= 0:
                        first_alto_idx = seq_alto_idx
                    j += 1
                else:
                    match_ok = False
                    break

            if match_ok and first_alto_idx is not None:
                bboxes[tok_idx] = alto_strings[first_alto_idx]
                pos = j  # advance read-head past the consumed chars
                break
            # else: try again from pos+skip+1

    return bboxes


def _bio_to_code(ner_tag):
    if not ner_tag or ner_tag in ('O', '_'):
        return ''
    primary = ner_tag.split('|')[0]
    if primary.startswith(('B-', 'I-')):
        return primary[2:]
    return ''


# Maps CNEC 2.0 type codes to the four CoNLL-style categories used in @type.
# @cnec carries the raw CNEC code; @type is used for querying / interop.
_CNEC_TO_CONLL = {
    # PER — personal names
    'p': 'PER', 'p_': 'PER', 'P': 'PER',
    'pf': 'PER', 'ps': 'PER', 'pm': 'PER',
    'ph': 'PER', 'pc': 'PER', 'pd': 'PER', 'pp': 'PER',
    # ORG — institutions and organisations
    'i': 'ORG', 'i_': 'ORG', 'I': 'ORG',
    'ia': 'ORG', 'if': 'ORG', 'io': 'ORG', 'ic': 'ORG',
    # LOC — geographical and place names
    'g': 'LOC', 'G': 'LOC', 'g_': 'LOC',
    'gu': 'LOC', 'gl': 'LOC', 'gq': 'LOC', 'gr': 'LOC',
    'gs': 'LOC', 'gc': 'LOC', 'gt': 'LOC', 'gh': 'LOC',
}


def _group_ner_spans(tokens):
    groups = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        ner = tok.get('ner', '')
        if ner and ner not in ('O', '_') and ner.startswith('B-'):
            span = [tok]
            i += 1
            while i < len(tokens):
                nxt = tokens[i].get('ner', '')
                if nxt and nxt.startswith('I-'):
                    span.append(tokens[i])
                    i += 1
                else:
                    break
            groups.append({'kind': 'name', 'tokens': span,
                           'code': _bio_to_code(ner)})
        else:
            groups.append({'kind': 'plain', 'tokens': [tok]})
            i += 1
    return groups


def _tok_xml(tok, id_map, indent=10):
    wid = id_map.get(tok['id'], tok['id'])

    # Skip head attribute entirely when token is root (head == '0')
    head_ref = None
    if tok.get('head') and tok['head'] != '0':
        head_ref = id_map.get(tok['head'], tok['head'])

    tok_type = 'pc' if tok.get('upos') == 'PUNCT' else 'w'

    attrs = [f'id="{wid}"', f'type="{tok_type}"']   # xml:id → id
    if tok.get('lemma') and tok['lemma'] != '_':
        attrs.append(f'lemma="{_attr(tok["lemma"])}"')
    if tok.get('upos') and tok['upos'] != '_':
        attrs.append(f'upos="{_attr(tok["upos"])}"')
    if tok.get('xpos') and tok['xpos'] != '_':
        attrs.append(f'xpos="{_attr(tok["xpos"])}"')
    if tok.get('feats') and tok['feats'] != '_':
        attrs.append(f'feats="{_attr(tok["feats"])}"')
    if head_ref is not None:
        attrs.append(f'head="{head_ref}"')
    if tok.get('deprel') and tok['deprel'] != '_':
        attrs.append(f'deprel="{_attr(tok["deprel"])}"')
    if not tok.get('space_after', True):
        attrs.append('join="right"')

    bbox = tok.get('_bbox')
    if bbox:
        attrs.append(f'bbox="{bbox["left"]} {bbox["top"]} {bbox["right"]} {bbox["bottom"]}"')

    pad = ' ' * indent
    return f'{pad}<tok {" ".join(attrs)}>{escape(tok["form"])}</tok>\n'


def write_teitok_merged(conllu_path, teitok_path, alto_path=None, doc_id=None):
    """
    Produce TEITOK XML from a NER-enriched CoNLL-U file.

    TEITOK conventions applied:
    - xmlnsoff= instead of xmlns= (TEITOK disables namespace processing)
    - id= instead of xml:id=  (same reason)
    - lang= instead of xml:lang=
    - <facsimile>/<surface lrx= lry=> carries page dimensions from ALTO
    - <pb facs="{doc_id}-{n}.png"> strict filename convention
    - head= omitted on root tokens
    - lemma= and text= attribute values fully quote-escaped
    """
    alto_strings, alto_pages = _parse_alto(alto_path)   # now use both returns

    # ── Parse CoNLL-U ────────────────────────────────────────────────────────
    sentences   = []
    current_tok = []
    sent_id, sent_text = None, None

    try:
        with open(conllu_path, 'r', encoding='utf-8') as f:
            for raw in f:
                line = raw.rstrip('\n')
                if line.startswith('# sent_id'):
                    sent_id   = line.split('=', 1)[1].strip() if '=' in line else None
                    continue
                if line.startswith('# text'):
                    sent_text = line.split('=', 1)[1].strip() if '=' in line else None
                    continue
                if not line.strip() or line.startswith('#'):
                    if not line.strip() and current_tok:
                        sentences.append({'id': sent_id, 'text': sent_text,
                                          'tokens': current_tok})
                        current_tok = []
                    continue
                cols = line.split('\t')
                if len(cols) < 10 or '-' in cols[0] or '.' in cols[0]:
                    continue
                misc = parse_misc(cols[9])
                current_tok.append({
                    'id':          cols[0],
                    'form':        cols[1],
                    'lemma':       cols[2],
                    'upos':        cols[3],
                    'xpos':        cols[4],
                    'feats':       cols[5],
                    'head':        cols[6],
                    'deprel':      cols[7],
                    'space_after': misc.get('SpaceAfter', 'Yes') != 'No',
                    'ner':         misc.get('NER', ''),
                })
        if current_tok:
            sentences.append({'id': sent_id, 'text': sent_text, 'tokens': current_tok})
    except Exception as e:
        print(f'  [Error] Reading CoNLL-U {conllu_path}: {e}', file=sys.stderr)
        return False

    # ── Align tokens to ALTO bboxes ──────────────────────────────────────────
    all_tokens = [tok for sent in sentences for tok in sent['tokens']]
    all_bboxes = _align_tokens_to_alto(all_tokens, alto_strings)
    tok_ptr = 0
    for sent in sentences:
        for tok in sent['tokens']:
            tok['_bbox'] = all_bboxes[tok_ptr]
            tok_ptr += 1

    matched = sum(1 for b in all_bboxes if b is not None)
    print(f'  [ALTO] matched {matched}/{len(all_tokens)} tokens to bboxes '
          f'({len(alto_strings)} ALTO strings)')

    # ── Write XML ────────────────────────────────────────────────────────────
    doc_id_safe  = escape(doc_id or Path(teitok_path).stem)
    current_page = 0

    try:
        with open(teitok_path, 'w', encoding='utf-8') as out:
            out.write('<?xml version="1.0" encoding="utf-8"?>\n')
            # TEITOK: xmlnsoff= disables namespace processing; lang= not xml:lang=
            out.write('<TEI xmlnsoff="http://www.tei-c.org/ns/1.0" lang="cs">\n')

            # ── teiHeader ────────────────────────────────────────────────────
            out.write('  <teiHeader/>\n')

            # ── facsimile block — page dimensions from ALTO, no image needed ─
            # TEI encodes page size via <surface lrx= lry=> (lower-right corner
            # = width/height when upper-left is implicitly 0,0).  This lets
            # TEITOK know the canvas size without requiring the image file.
            if alto_pages:
                out.write('  <facsimile>\n')
                for pg_idx, pg in enumerate(alto_pages, start=1):
                    surf_id  = f'{doc_id_safe}.pb{pg_idx}'
                    facs_img = f'{doc_id_safe}-{pg_idx}.png'   # strict convention
                    lrx_attr = f' lrx="{pg["width"]}"'  if pg.get('width')  else ''
                    lry_attr = f' lry="{pg["height"]}"' if pg.get('height') else ''
                    out.write(f'    <surface id="{surf_id}"{lrx_attr}{lry_attr}>\n')
                    out.write(f'      <graphic url="{facs_img}"/>\n')
                    out.write( '    </surface>\n')
                out.write('  </facsimile>\n')

            # ── text body ────────────────────────────────────────────────────
            out.write('  <text>\n    <body>\n')
            out.write(f'      <div type="document" id="{doc_id_safe}">\n')

            for s_idx, sent in enumerate(sentences, start=1):
                # New page when sent_id resets to '1'
                if sent.get('id') == '1':
                    current_page += 1
                    pb_id   = f'{doc_id_safe}.pb{current_page}'
                    facs    = f'{doc_id_safe}-{current_page}.png'   # strict convention
                    # facs="#pb_id" if we emitted a <facsimile>; plain filename otherwise
                    facs_ref = f'#{pb_id}' if alto_pages else facs
                    out.write(f'        <pb n="{current_page}"'
                              f' id="{pb_id}"'
                              f' facs="{facs_ref}"/>\n')

                sid       = escape(f'{doc_id_safe}.s{s_idx}')
                # text attribute: must escape quotes inside the value
                text_attr = f' text="{_attr(sent["text"])}"' if sent.get('text') else ''
                out.write(f'        <s id="{sid}"{text_attr}>\n')   # xml:id → id

                id_map = {t['id']: f'{sid}.w{t["id"]}' for t in sent['tokens']}
                groups = _group_ner_spans(sent['tokens'])

                for grp in groups:
                    if grp['kind'] == 'name':
                        code      = grp['code']
                        conll_cat = _CNEC_TO_CONLL.get(code, 'MISC')
                        out.write(f'          <name type="{escape(conll_cat)}"'
                                  f' cnec="{escape(code)}">\n')
                        for tok in grp['tokens']:
                            out.write('  ' + _tok_xml(tok, id_map, indent=12))
                        out.write('          </name>\n')   # was </n> — typo fixed
                    else:
                        out.write(_tok_xml(grp['tokens'][0], id_map, indent=10))

                out.write('        </s>\n')

            out.write('      </div>\n    </body>\n  </text>\n</TEI>\n')
        return True
    except Exception as e:
        print(f'  [Error] Writing TEITOK {teitok_path}: {e}', file=sys.stderr)
        return False

# === New helper: parse boolean-like env/arg values ===
def bool_from_str(s, default=False):
    if s is None:
        return default
    if isinstance(s, bool):
        return s
    s = str(s).strip().lower()
    return s in ('1', 'true', 'yes', 'y', 'on')


def process_pipeline(conllu_dir, tsv_root, output_root, alto_root, teitok_out,
                     save_conllu=True, save_csv=True, save_teitok=False):
    conllu_path_obj = Path(conllu_dir)
    tsv_root_obj    = Path(tsv_root)
    output_root_obj = Path(output_root)

    if not conllu_path_obj.exists():
        print(f"Error: CoNLL-U dir not found: {conllu_dir}")
        sys.exit(1)

    # Guard: teitok_out may be None when save_teitok=False (args.tt_dir not set)
    teitok_out_path = Path(teitok_out) if teitok_out else None
    if save_teitok:
        if teitok_out_path is None:
            print("Error: teitok_out directory required when save_teitok=True")
            sys.exit(1)
        teitok_out_path.mkdir(parents=True, exist_ok=True)  # ensure it exists

    conllu_files = sorted(list(conllu_path_obj.glob('*.conllu')))
    print(f"Found {len(conllu_files)} documents to process.")
    output_root_obj.mkdir(parents=True, exist_ok=True)

    for conllu_file in conllu_files:
        doc_name = conllu_file.stem

        doc_out_dir    = output_root_obj / doc_name
        doc_out_conllu = doc_out_dir / f"{doc_name}.conllu"
        doc_out_csv    = doc_out_dir / f"{doc_name}.csv"
        # Only construct teitok path when the directory is known
        doc_out_teitok = (teitok_out_path / f"{doc_name}.teitok.xml") if teitok_out_path else None
        doc_in_alto    = Path(alto_root) / f"{doc_name}.alto.xml" if alto_root else None

        need_conllu = save_conllu and not doc_out_conllu.exists()
        need_csv    = save_csv    and not doc_out_csv.exists()
        need_teitok = save_teitok and doc_out_teitok is not None and not doc_out_teitok.exists()
        need_merge  = need_conllu or need_csv or need_teitok

        if not need_merge:
            print(f"[Skip] {doc_name}: all requested outputs already exist.")
            continue

        doc_tsv_dir = tsv_root_obj / doc_name
        if not doc_tsv_dir.exists() or not doc_tsv_dir.is_dir():
            print(f"[Skip] No TSV directory found for: {doc_name} (checked {doc_tsv_dir})")
            continue

        print(f"[Processing] {doc_name}...")
        doc_out_dir.mkdir(parents=True, exist_ok=True)

        merged_conllu_ready = doc_out_conllu.exists()

        if not merged_conllu_ready:
            tsv_data = get_sorted_tsv_content(doc_tsv_dir)
            if not tsv_data:
                print(f"  [Warn] No valid TSV data found in {doc_tsv_dir}")
                continue
            merged_conllu_ready = merge_and_write(conllu_file, tsv_data, doc_out_conllu)
            if not merged_conllu_ready:
                print(f"  [Error] Failed to create merged CoNLL-U for {doc_name}, skipping.")
                continue

        if need_csv:
            process_merged_file(doc_out_conllu, doc_out_csv)

        if need_teitok:
            write_teitok_merged(doc_out_conllu, doc_out_teitok,
                                doc_in_alto, doc_id=doc_name)

        if not save_conllu:
            csv_done    = not save_csv    or doc_out_csv.exists()
            teitok_done = not save_teitok or (doc_out_teitok is not None and doc_out_teitok.exists())
            if csv_done and teitok_done:
                try:
                    doc_out_conllu.unlink()
                except Exception as e:
                    print(f"  [Warn] Could not remove intermediate CoNLL-U "
                          f"{doc_out_conllu}: {e}", file=sys.stderr)

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
    parser.add_argument('--tt-dir', default=os.getenv('TEITOK_OUTPUT_DIR'))
    parser.add_argument('--alto-dir', default=os.getenv('ALTO_DIR'))

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

    if save_teitok:
        if not Path(args.alto_dir).exists():
            print(f"ALTO XML directory is required for complete TEITOK XML generation.")
            sys.exit(1)
        if not Path(args.tt_dir).exists():
            print(f"TEITOK output directory is required for complete TEITOK XML generation.")
            print(f"Creating default: {args.tt_dir}")
            Path(args.tt_dir).mkdir(parents=True, exist_ok=True)



    process_pipeline(args.conllu_dir, args.tsv_dir, args.out_dir, args.alto_dir, args.tt_dir,
                     save_conllu=save_conllu, save_csv=save_csv, save_teitok=save_teitok)



if __name__ == "__main__":
    main()