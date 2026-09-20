def run_length_encode(input_string: str):
    if not input_string:
        return ""
    encoded_string = ""
    count = 1
    for i in range(1, len(input_string)):
        if input_string[i] == input_string[i - 1]:
            count += 1
        else:
            encoded_string += str(count) + input_string[i - 1]
            count = 1
    encoded_string += str(count) + input_string[-1]
    return encoded_string


original_data = "AAAAABBBCCCDDDDD"
compressed_data = run_length_encode(original_data)
print(f"Original: {original_data}")
print(f"Compressed (RLE): {compressed_data}")
