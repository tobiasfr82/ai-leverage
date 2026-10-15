"""ai-leverage/src/python/gguf_names.py

How GGUF files are named, read the way llama.cpp reads them: which files are
one size of a model, which part of it each one is, and which file next to it
lets the model read images. A GGUF model's page usually holds a dozen sizes:

  gpt-oss-120b-Q4_K_M-00001-of-00002.gguf   part 1 of 2 of size Q4_K_M
  Q8_0/gpt-oss-120b-Q8_0.gguf               size Q8_0, in one file
  mmproj-F16.gguf                           lets the model read images

The downloader (gguf_files.py: which files to fetch) and model_facts.py (what
is downloaded, for the fit and llama.cpp's list_models) both go by these
rules, so they agree on what a model is and what it's called. Only the
standard library, so the downloader's Python and the system's both run it.
"""

import re

# "name-00001-of-00003": part 1 of a model split into 3 files
SPLIT = re.compile(r"(.+)-(\d{5})-of-(\d{5})", re.IGNORECASE)
# The size is the last part of the name: "gpt-oss-120b-Q4_K_M" -> Q4_K_M
SIZE = re.compile(r"[-.]([A-Z0-9_]+)$", re.IGNORECASE)
# Files next to a model that aren't a model themselves
SIDE_FILES = ("mmproj", "imatrix", "mtp-", "eagle3-", "dflash-", "dspark-")


def split_info(path):
    """A .gguf file's name without the part number, its size, and part x of y"""
    name = path.removesuffix(".gguf")
    part, parts = 1, 1
    if match := SPLIT.fullmatch(name):
        name, part, parts = match[1], int(match[2]), int(match[3])
    size = SIZE.search(name)
    return name, size[1].upper() if size else "", part, parts


def is_model(path):
    file_name = path.rsplit("/", 1)[-1]
    return path.endswith(".gguf") and not any(side in file_name for side in SIDE_FILES)


def is_image_file(path):
    return path.endswith(".gguf") and "mmproj" in path.rsplit("/", 1)[-1]


def bits(size):
    """4 for Q4_K_M, 16 for F16: how llama.cpp matches an image file to a size"""
    digits = re.search(r"\d+", size)
    return int(digits[0]) if digits else 0


def sizes_on_page(files):
    """The sizes these files hold, in the order they come"""
    sizes = []
    for path in files:
        _, size, part, _ = split_info(path)
        if is_model(path) and part == 1 and size and size not in sizes:
            sizes.append(size)
    return sizes


def first_part(files, size):
    """The model file llama.cpp loads for "organization/model:size": the first
    that names the size, e.g. UD-Q4_K_XL in ...-UD-Q4_K_XL-00001-of-00002.gguf.
    None when no file names it."""
    names_it = re.compile(re.escape(size) + r"[.-]", re.IGNORECASE)
    for path in files:
        if is_model(path) and names_it.search(path):
            _, _, part, parts = split_info(path)
            if parts == 1 or part == 1:
                return path
    return None


def all_parts(files, first):
    """Every part of the model that first is part 1 of, the ones there are"""
    name, _, _, parts = split_info(first)
    if parts == 1:
        return [first]
    return [p for p in files if p.endswith(".gguf") and split_info(p)[0] == name and split_info(p)[3] == parts]


def by_size(files):
    """The models among these files, one per size: {size: (its parts that
    are there, how many parts it has)}. When two names give one size, the
    first one's files count."""
    found = {}
    for path in files:
        name, size, _, parts = split_info(path)
        if not is_model(path) or not size:
            continue
        entry = found.setdefault(size, (name, parts, []))
        if entry[0] == name:
            entry[2].append(path)
    return {size: (sorted(paths), parts) for size, (_, parts, paths) in found.items()}


def image_file(files, model):
    """The file that lets the model read images, if any. Like llama.cpp: one in
    the model's own folder or a folder above it, nearest first, then the one
    whose precision is closest to the model's."""
    model_folders = model.split("/")[:-1]
    model_bits = bits(split_info(model)[1])
    best, best_rank = None, None
    for path in files:
        if not is_image_file(path):
            continue
        folders = path.split("/")[:-1]
        if folders != model_folders[: len(folders)]:
            continue
        rank = (len(folders), -abs(bits(split_info(path)[1]) - model_bits))
        if best is None or rank > best_rank:
            best, best_rank = path, rank
    return best
