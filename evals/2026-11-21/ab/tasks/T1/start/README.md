# wordtop

Prints the most frequent words of the given text files (or stdin).

    python3 wordtop.py --top 5 data/sample.txt

Output: one line per word, `<count> <word>`. Words are casefolded and
punctuation is stripped. Stdlib only.
