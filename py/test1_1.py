import persian
import string

for char in string.ascii_lowercase:
    print(f"{char}->{persian.convert_en_characters(char)}")
