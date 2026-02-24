# api_util/analyze.py
import re
import sys
import os
import csv
from collections import Counter

# Increase field limit for large CSVs
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


def parse_tag_and_type_tsv(raw_tag):
    if raw_tag == "O" or not raw_tag:
        return "O", None

    if raw_tag.startswith("B-") or raw_tag.startswith("I-"):
        primary = raw_tag.split('|')[0]
        prefix = primary[:2]
        short_code = primary[2:]

        full_type_name = CNEC_TYPE_MAP.get(short_code, f"Unknown Code ({short_code})")
        return primary, full_type_name

    return "O", None


def get_entities_from_tsv(tsv_path):
    entities = []
    curr_toks = []
    curr_type = None

    try:
        with open(tsv_path, 'r', encoding='utf-8') as f:
            first_line = next(f, "").strip()
            if not first_line: return []

            if not first_line.startswith("Word"):
                f.seek(0)

            for line in f:
                line = line.strip()
                if not line: continue

                parts = line.split('\t')
                if len(parts) < 2: continue

                tok = parts[0]
                tag_raw = parts[1]

                bio_tag, full_etype = parse_tag_and_type_tsv(tag_raw)

                if bio_tag.startswith('B') or (bio_tag != 'O' and not curr_toks):
                    if curr_toks:
                        entities.append((" ".join(curr_toks), curr_type))
                    curr_toks = [tok]
                    curr_type = full_etype

                elif bio_tag.startswith('I') and curr_toks:
                    curr_toks.append(tok)

                else:
                    if curr_toks:
                        entities.append((" ".join(curr_toks), curr_type))
                        curr_toks = []
                        curr_type = None

            if curr_toks:
                entities.append((" ".join(curr_toks), curr_type))

    except Exception as e:
        print(f"[Error] parsing {os.path.basename(tsv_path)}: {e}", file=sys.stderr)

    return entities


def extract_page_number(filename):
    match = re.search(r'-(\d+)\.tsv$', filename)
    if match:
        return int(match.group(1))
    return 0


def main():
    if len(sys.argv) < 3:
        print("Usage: analyze.py <input_ne_root_dir> <stats_file>")
        sys.exit(1)

    input_root_dir = sys.argv[1]
    stats_file = sys.argv[2]
    top_n = 20

    os.makedirs(os.path.dirname(stats_file), exist_ok=True)
    print(f"[Stats] Scanning entities in: {input_root_dir}")

    with open(stats_file, 'w', newline='', encoding='utf-8-sig') as f:
        # Added QUOTE_ALL to prevent parsing errors due to special characters like hyphens
        w = csv.writer(f, quoting=csv.QUOTE_ALL, quotechar='"')
        header = ["file", "page"] + [x for i in range(1, top_n + 1) for x in (f"ne{i}", f"type{i}", f"cnt-{i}")]
        w.writerow(header)

        if os.path.exists(input_root_dir):
            doc_dirs = sorted([d for d in os.listdir(input_root_dir) if os.path.isdir(os.path.join(input_root_dir, d))])
            count_processed = 0

            for doc_name in doc_dirs:
                doc_path = os.path.join(input_root_dir, doc_name)
                tsv_files = sorted([f for f in os.listdir(doc_path) if f.endswith(".tsv")])

                if not tsv_files:
                    continue

                for tsv_file in tsv_files:
                    full_path = os.path.join(doc_path, tsv_file)
                    page_num = extract_page_number(tsv_file)
                    entities = get_entities_from_tsv(full_path)

                    if not entities:
                        continue

                    c = Counter(entities).most_common(top_n)

                    row = [doc_name, page_num]
                    for (ne_text, ne_type), cnt in c:
                        row.extend([ne_text, ne_type, cnt])

                    missing = top_n - len(c)
                    if missing > 0:
                        row.extend(["", "", 0] * missing)

                    w.writerow(row)

                count_processed += 1

            print(f"[Stats] Processed {count_processed} documents.")
            print(f"[Stats] Saved to {stats_file}")


if __name__ == "__main__":
    main()