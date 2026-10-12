# ai-leverage/stack/downloaders/huggingface/gguf_files.py
# Works out which files of a GGUF model make up one size, for sync_models.sh.
# A GGUF model's page usually holds a dozen sizes of the same model
# (unsloth/gpt-oss-120b-GGUF: 15 sizes, about 1 TB in all), so a line in
# models.txt names the one it wants, e.g. "unsloth/gpt-oss-120b-GGUF:Q4_K_M".
#
# It picks the files the way llama.cpp does when it loads "organization/model:size"
# (common/download.cpp in llama.cpp), so what gets downloaded is exactly what
# llama.cpp runs: every part of that size, plus the file that lets the model
# read images, if the page has one.
#
# Usage: gguf_files.py <organization/model> <size>    the files, one per line
#        gguf_files.py <organization/model> --sizes   the sizes the page has

import re
import sys

from huggingface_hub import HfApi, RepoFile
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

# "name-00001-of-00003": part 1 of a model split into 3 files
SPLIT = re.compile(r"(.+)-(\d{5})-of-(\d{5})", re.IGNORECASE)
# The size is the last part of the name: "gpt-oss-120b-Q4_K_M" -> Q4_K_M
SIZE = re.compile(r"[-.]([A-Z0-9_]+)$", re.IGNORECASE)
# Files next to a model that aren't a model themselves
SIDE_FILES = ("mmproj", "imatrix", "mtp-", "eagle3-", "dflash-", "dspark-")


def split_info(path):
    """A .gguf file's name without the part number, its size, and part x of y."""
    name = path.removesuffix(".gguf")
    part, parts = 1, 1
    if match := SPLIT.fullmatch(name):
        name, part, parts = match[1], int(match[2]), int(match[3])
    size = SIZE.search(name)
    return name, size[1].upper() if size else "", part, parts


def is_model(path):
    file_name = path.rsplit("/", 1)[-1]
    return path.endswith(".gguf") and not any(side in file_name for side in SIDE_FILES)


def bits(path):
    """4 for Q4_K_M, 16 for F16: how llama.cpp matches an image file to a size."""
    digits = re.search(r"\d+", split_info(path)[1])
    return int(digits[0]) if digits else 0


def first_part(files, size):
    """The model file llama.cpp loads for a size: the first that names it."""
    names_it = re.compile(re.escape(size) + r"[.-]", re.IGNORECASE)
    for path in files:
        if is_model(path) and names_it.search(path):
            _, _, part, parts = split_info(path)
            if parts == 1 or part == 1:
                return path
    return None


def all_parts(files, first):
    name, _, _, parts = split_info(first)
    if parts == 1:
        return [first]
    return [p for p in files if p.endswith(".gguf") and split_info(p)[0] == name and split_info(p)[3] == parts]


def image_file(files, model):
    """The file that lets the model read images, if any. Like llama.cpp: one in
    the model's own folder or a folder above it, nearest first, then the one
    whose precision is closest to the model's."""
    model_folders = model.split("/")[:-1]
    best, best_rank = None, None
    for path in files:
        if not path.endswith(".gguf") or "mmproj" not in path:
            continue
        folders = path.split("/")[:-1]
        if folders != model_folders[: len(folders)]:
            continue
        rank = (len(folders), -abs(bits(path) - bits(model)))
        if best is None or rank > best_rank:
            best, best_rank = path, rank
    return best


def sizes_on_page(files):
    sizes = []
    for path in files:
        _, size, part, _ = split_info(path)
        if is_model(path) and part == 1 and size and size not in sizes:
            sizes.append(size)
    return sizes


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
