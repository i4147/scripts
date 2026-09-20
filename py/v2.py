import os
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

API_ID = "38250819"
API_HASH = "9d40fb6a0e2fbd00caa15122d2c7c283"


SESSION_NAME = "my_telegram_session"


async def main():
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    print("Подключение к Telegram...")
    await client.start()
    print("Успешно авторизовано!")

    channels_links = []
    groups_links = []

    print("Сканирование ваших чатов и каналов...")

    
    async for dialog in client.iter_dialogs():
        entity = dialog.entity

        
        if isinstance(entity, Channel):
            
            if entity.username:
                link = f"https://t.me/{entity.username}"
            else:
                
                link = f"https://t.me/c/{entity.id}/1"

            
            if entity.megagroup or isinstance(entity, Chat):
                groups_links.append(f"{dialog.name} : {link}")
            else:
                channels_links.append(f"{dialog.name} : {link}")

        elif isinstance(entity, Chat):
            
            link = f"https://t.me/c/{entity.id}/1"
            groups_links.append(f"{dialog.name} : {link}")

    
    channels_filename = "channels.txt"
    with open(channels_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(channels_links))
    print(f"Найдено каналов: {len(channels_links)}. Сохранено в '{channels_filename}'")

    
    groups_filename = "groups.txt"
    with open(groups_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(groups_links))
    print(f"Найдено групп: {len(groups_links)}. Сохранено в '{groups_filename}'")

    print("Готово!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
