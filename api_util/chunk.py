import sys
import os


def write_chunk(output_dir, chunk_index, words_list):
    """Helper to write a list of words to a file."""
    filename = os.path.join(output_dir, f"chunk_{chunk_index}.txt")
    with open(filename, 'w', encoding='utf-8') as out:
        out.write(" ".join(words_list))


def main():
    # Basic argument validation
    if len(sys.argv) < 4:
        print("Usage: chunk.py <infile> <outdir> <word_limit>")
        sys.exit(1)

    infile = sys.argv[1]
    outdir = sys.argv[2]
    limit = int(sys.argv[3])

    # Ensure output directory exists
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    # Read the full text extracted from CSV
    with open(infile, 'r', encoding='utf-8') as f:
        text = f.read().strip()

    if not text:
        sys.exit(0)

    # Split by whitespace to get words
    words = text.split()
    current_chunk = []
    chunk_count = 0

    i = 0
    while i < len(words):
        current_chunk.append(words[i])
        i += 1

        # Check if buffer reached limit
        if len(current_chunk) >= limit:
            cut_index = -1

            # Intelligent splitting: look back for punctuation to avoid cutting mid-sentence
            lookback_limit = max(0, len(current_chunk) - 100)

            for j in range(len(current_chunk) - 1, lookback_limit, -1):
                word = current_chunk[j]
                if word and word[-1] in ['.', '?', '!']:
                    cut_index = j + 1
                    break

            # Fallback to hard limit if no punctuation found
            if cut_index == -1:
                cut_index = len(current_chunk)

            write_chunk(outdir, chunk_count, current_chunk[:cut_index])
            chunk_count += 1

            # Move leftovers to next chunk
            current_chunk = current_chunk[cut_index:]

    # Write final chunk
    if current_chunk:
        write_chunk(outdir, chunk_count, current_chunk)


if __name__ == "__main__":
    main()