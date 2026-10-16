import click

from .PDFParserClass import *

obj_parser = PDFparser()


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--output_file",
    "-o",
    type=str,
    default="pdf_output.txt",
    help="Name of the output file",
)
def pdftotext(input_file, output_file) -> None:
    obj_parser.pdftotext(input_file, output_file)


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--output_file",
    "-o",
    type=str,
    default="pdf_output.json",
    help="Name of the output file",
)
def pdftojson(input_file, output_file) -> None:
    obj_parser.simplePdftoJson(input_file, output_file)


@cli.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.option(
    "--output_file",
    "-o",
    type=str,
    default="pdf_output.jsonl",
    help="Name of the output file",
)
def pdftojsonl(input_file, output_file) -> None:
    obj_parser.pdftojsonl(input_file, output_file)


if __name__ == "__main__":
    cli()
