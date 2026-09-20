async def detect_languages():
    async with Translator() as translator:
        result = await translator.detect("이 문장은 한글로 쓰여졌습니다.")
        print(result)
        result = await translator.detect("この文章は日本語で書かれました。")
        print(result)
        result = await translator.detect("This sentence is written in English.")
        print(result)
        result = await translator.detect("Tiu frazo estas skribita en Esperanto.")
        print(result)


asyncio.run(detect_languages())
