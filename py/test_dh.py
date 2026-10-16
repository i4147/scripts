# pip install deep-translator
from deep_translator import GoogleTranslator

translated = GoogleTranslator(source="auto", target="es").translate("Hello world")
print(translated)  # Output: Hola mundo
