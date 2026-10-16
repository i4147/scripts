import os
import brotlicffi
from joblib import Parallel, delayed
from rich.console import Console
from rich.text import Text

console = Console()


def compress_file_task(filepath, current_dir: str, output_base_dir: str):
    try:
        relative_path = os.path.relpath(filepath, current_dir)
        output_sub_dir = os.path.join(output_base_dir, os.path.dirname(relative_path))
        os.makedirs(output_sub_dir, exist_ok=True)
        original_size = os.path.getsize(filepath)
        compressed_filepath = os.path.join(output_sub_dir, os.path.basename(filepath) + ".br")
        with open(filepath, "rb") as f_in:
            data = f_in.read()
        with open(compressed_filepath, "wb") as f_out:
            compressed_data = brotlicffi.compress(data, quality=11)
            f_out.write(compressed_data)
        compressed_size = os.path.getsize(compressed_filepath)
        if os.path.exists(compressed_filepath) and compressed_size > 0:
            os.remove(filepath)
            console.log(
                f"[green]Compressed and deleted original:[/green] [cyan]{filepath}[/cyan] -> [yellow]{compressed_filepath}[/yellow]"
            )
            return {
                "success": True,
                "filepath": filepath,
                "original_size": original_size,
                "compressed_size": compressed_size,
            }
        else:
            if os.path.exists(compressed_filepath):
                os.remove(compressed_filepath)
            console.log(f"[bold red]Failed to compress (empty output) {filepath}. Original not deleted.[/bold red]")
            return {
                "success": False,
                "filepath": filepath,
                "original_size": original_size,
                "compressed_size": 0,
            }
    except Exception as e:
        console.log(f"[bold red]Error compressing {filepath}:[/bold red] {e}")
        return {
            "success": False,
            "filepath": filepath,
            "original_size": 0,
            "compressed_size": 0,
        }


def get_all_files(directory: str):
    file_list = []
    for root, _, files in os.walk(directory):
        for filename in files:
            file_list.append(os.path.join(root, filename))
    return file_list


def main() -> None:
    current_dir = os.getcwd()
    output_base_dir = os.path.join(current_dir, "compressed_files")
    all_files = get_all_files(current_dir)
    files_to_compress = []
    for f in all_files:
        if not f.endswith(".br") and not f.startswith(output_base_dir):
            files_to_compress.append(f)
    if not files_to_compress:
        console.print("[bold yellow]No files found to compress in the current directory.[/bold yellow]")
        return
    console.print(
        f"[bold blue]Found {len(files_to_compress)} files to compress. Starting parallel compression...[/bold blue]"
    )
    results = Parallel(n_jobs=-1, verbose=10)(
        delayed(compress_file_task)(filepath, current_dir, output_base_dir) for filepath in files_to_compress
    )
    successful_compressions = 0
    total_original_size = 0
    total_compressed_size = 0
    for result in results:
        if result["success"]:
            successful_compressions += 1
            total_original_size += result["original_size"]
            total_compressed_size += result["compressed_size"]
    console.print(Text("\n" + "=" * 40, style="bold blue"))
    console.print("[bold green]Compression Summary:[/bold green]")
    console.print(f"Total files processed: {len(files_to_compress)}")
    console.print(f"Successfully compressed and deleted originals: {successful_compressions}")
    console.print(f"Failed compressions: {len(files_to_compress) - successful_compressions}")
    if total_original_size > 0:
        reduction_percent = ((total_original_size - total_compressed_size) / total_original_size) * 100
        console.print(f"Total original size: {total_original_size / (1024 * 1024):.2f} MB")
        console.print(f"Total compressed size: {total_compressed_size / (1024 * 1024):.2f} MB")
        console.print(f"[bold green]Total size reduction: {reduction_percent:.2f}%[/bold green]")
    else:
        console.print("No data was successfully compressed to calculate reduction.")
    console.print(f"[bold magenta]Compressed files are saved in the '{output_base_dir}' directory.[/bold magenta]")
    console.print(Text("=" * 40, style="bold blue"))


if __name__ == "__main__":
    main()
