from pathlib import Path
import glob
import os
import warnings


def _process_input_path(path_to_data: (Path, str)) -> Path:
    if isinstance(path_to_data, str):
        path_to_data = Path(path_to_data)
    if not isinstance(path_to_data, Path):
        raise TypeError(f"path_to_data must be type Path or str, not {type(path_to_data)}")
    if not path_to_data.is_dir():
        raise NotADirectoryError(f"invalid path supplied; {path_to_data} does not exist")
    return path_to_data


def _process_extensions(file_extensions: (str, list)) -> list:
    if isinstance(file_extensions, str):
        file_extensions = [file_extensions]
    if not isinstance(file_extensions, list):
        raise TypeError(f"file_extensions must be type str or list, not {type(file_extensions)}")
    processed_extensions = []
    for extension in file_extensions:
        if not extension[0] == ".":
            extension = "." + extension
        processed_extensions.append(extension)
    return processed_extensions


def _get_all_files(
    path_to_data: (Path, str),
    file_extensions: (str, list),
    file_name: str = "*",
    sorted: bool = True,
    return_absolute_filepath: bool = False,
) -> list:
    path_to_data = _process_input_path(path_to_data)
    file_extensions = _process_extensions(file_extensions)
    Files = []
    for extension in file_extensions:
        search_string = file_name + extension
        AllFiles = glob.glob(str(path_to_data / search_string))
        for file in AllFiles:
            if return_absolute_filepath:
                Files.append(file)
            else:
                head, tail = os.path.split(file)
                Files.append(tail)
        if not Files:
            warnings.warn(f"\nno files matching {search_string} in {path_to_data}\n")
    if sorted:
        Files.sort()
    return Files
