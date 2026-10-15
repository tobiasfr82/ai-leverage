# ai-leverage/stack/downloaders/huggingface/gguf_files.py
# Works out which files of a GGUF model make up one size, for sync_models.sh.
# A GGUF model's page usually holds a dozen sizes of the same model
# (unsloth/gpt-oss-120b-GGUF: 15 sizes, about 1 TB in all), so a line in
# models.txt names the one it wants, e.g. "unsloth/gpt-oss-120b-GGUF:Q4_K_M".
#
# It picks the files the way llama.cpp does when it loads "organization/model:size"
# (common/download.cpp in llama.cpp), so what gets downloaded is exactly what
# llama.cpp runs: every part of that size, plus the file that lets the model
# read images, if the page has one. The naming rules for that are in
# src/python/gguf_names.py.
#
# Usage: gguf_files.py <organization/model> <size>    the files, one per line
#        gguf_files.py <organization/model> --sizes   the sizes the page has

import os
import re
import sys

from huggingface_hub import HfApi, RepoFile
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

# The naming rules are shared with the model fit and llama.cpp's list_models
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src", "python"))
from gguf_names import all_parts, first_part, image_file, sizes_on_page  # noqa: E402


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: gguf_files.py <organization/model> <size | --sizes>")
    repo, size = sys.argv[1], sys.argv[2]

    try:
        # HF_TOKEN from .env is picked up for gated models
        tree = HfApi().list_repo_tree(repo, recursive=True)
        file_sizes = {item.path: item.size for item in tree if isinstance(item, RepoFile)}
    except GatedRepoError:
        sys.exit(f"{repo} is gated: accept its terms on huggingface.co and set HF_TOKEN in .env.")
    except RepositoryNotFoundError:
        sys.exit(f"{repo} isn't on huggingface.co. Check the name; a gated model also needs HF_TOKEN in .env.")
    except Exception as error:
        sys.exit(f"Can't read {repo} on huggingface.co: {str(error).splitlines()[0]}")
    files = list(file_sizes)
    sizes = sizes_on_page(files)

    if size == "--sizes":
        if not sizes:
            sys.exit(1)
        print(", ".join(sizes))
        return

    if not re.fullmatch(r"[A-Za-z0-9_-]+", size):
        sys.exit(f"'{size}' isn't a size. Sizes look like Q4_K_M or Q8_0.")
    first = first_part(files, size)
    if first is None:
        if sizes:
            sys.exit(f"{repo} has no size {size}. Its sizes: {', '.join(sizes)}")
        sys.exit(f"{repo} has no GGUF files.")

    download = all_parts(files, first)
    if image := image_file(files, first):
        download.append(image)
    total = sum(file_sizes[path] for path in download) / 1e9
    print(f"{repo}:{size}: {len(download)} file(s), {total:.1f} GB", file=sys.stderr)
    print("\n".join(download))


if __name__ == "__main__":
    main()
