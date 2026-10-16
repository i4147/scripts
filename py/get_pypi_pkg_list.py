from aiohttp.client import ClientSession
from aiofiles.threadpool.text import AsyncTextIOWrapper
import asyncio

import aiofiles
import aiohttp
from bs4 import BeautifulSoup

URL = "https://pypi.org/simple/"
OUTPUT_FILE = "pypi_packages.txt"
CHUNK_SIZE = 8192


async def stream_and_extract(session: ClientSession, url: str, outfile: AsyncTextIOWrapper):
    buffer = ""
    async for chunk in session.get(url).content.iter_chunked(CHUNK_SIZE):
        text = chunk.decode(errors="ignore")
        buffer += text
        *lines, buffer = buffer.split("\n")
        for line in lines:
            soup = BeautifulSoup(line, "html.parser")
            for a in soup.find_all("a"):
                await outfile.write(a.text + "\n")
    if buffer.strip():
        soup = BeautifulSoup(buffer, "html.parser")
        for a in soup.find_all("a"):
            await outfile.write(a.text + "\n")


async def main():
    async with (
        aiohttp.ClientSession() as session,
        aiofiles.open(OUTPUT_FILE, "w", encoding="utf-8") as outfile,
    ):
        await stream_and_extract(session, URL, outfile)
    print("Package list saved to", OUTPUT_FILE)


if __name__ == "__main__":
    asyncio.run(main())
