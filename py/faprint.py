


PERSIAN_LETTERS = {
    "ا": ("\u0627", "\ufe8d", "\ufe8e", "\ufe8e"),  
    "ب": ("\u0628", "\ufe8f", "\ufe91", "\ufe90"),  
    "پ": ("\u067e", "\ufb56", "\ufb58", "\ufb57"),  
    "ت": ("\u062a", "\ufe95", "\ufe97", "\ufe96"),  
    "ث": ("\u062b", "\ufe99", "\ufe9b", "\ufe9a"),  
    "ج": ("\u062c", "\ufe9d", "\ufe9f", "\ufe9e"),  
    "چ": ("\u0686", "\ufb7a", "\ufb7c", "\ufb7b"),  
    "ح": ("\u062d", "\ufea1", "\ufea3", "\ufea2"),  
    "خ": ("\u062e", "\ufea5", "\ufea7", "\ufea6"),  
    "د": ("\u062f", "\ufea9", "\ufeaa", "\ufeaa"),  
    "ذ": ("\u0630", "\ufeab", "\ufeac", "\ufeac"),  
    "ر": ("\u0631", "\ufead", "\ufeae", "\ufeae"),  
    "ز": ("\u0632", "\ufeaf", "\ufeb0", "\ufeb0"),  
    "ژ": ("\u0698", "\ufb8a", "\ufb8b", "\ufb8b"),  
    "س": ("\u0633", "\ufeb1", "\ufeb3", "\ufeb2"),  
    "ش": ("\u0634", "\ufeb5", "\ufeb7", "\ufeb6"),  
    "ص": ("\u0635", "\ufeb9", "\ufebb", "\ufeba"),  
    "ض": ("\u0636", "\ufebd", "\ufebf", "\ufebe"),  
    "ط": ("\u0637", "\ufec1", "\ufec3", "\ufec2"),  
    "ظ": ("\u0638", "\ufec5", "\ufec7", "\ufec6"),  
    "ع": ("\u0639", "\ufec9", "\ufecb", "\ufeca"),  
    "غ": ("\u063a", "\ufecd", "\ufecf", "\ufece"),  
    "ف": ("\u0641", "\ufed1", "\ufed3", "\ufed2"),  
    "ق": ("\u0642", "\ufed5", "\ufed7", "\ufed6"),  
    "ک": ("\u06a9", "\ufb8e", "\ufb90", "\ufb8f"),  
    "گ": ("\u06af", "\ufb92", "\ufb94", "\ufb93"),  
    "ل": ("\u0644", "\ufedf", "\ufee1", "\ufee0"),  
    "م": ("\u0645", "\ufee3", "\ufee5", "\ufee4"),  
    "ن": ("\u0646", "\ufee7", "\ufee9", "\ufee8"),  
    "و": ("\u0648", "\ufeee", "\ufeef", "\ufeef"),  
    "ه": ("\u0647", "\ufeeb", "\ufeed", "\ufeec"),  
    "ی": ("\u06cc", "\ufbfc", "\ufbfe", "\ufbfd"),  
    " ": (" ", " ", " ", " "),  
}


NON_CONNECTING = {"ا", "د", "ذ", "ر", "ز", "ژ", "و"}


def reshape_word(word: str) -> str:
    reshaped = []
    length = len(word)
    for i, char in enumerate(word):
        if char not in PERSIAN_LETTERS:
            reshaped.append(char)
            continue

        prev_char = word[i - 1] if i > 0 else ""
        next_char = word[i + 1] if i < length - 1 else ""

        connects_prev = prev_char and prev_char not in NON_CONNECTING and prev_char in PERSIAN_LETTERS
        connects_next = next_char and char not in NON_CONNECTING and next_char in PERSIAN_LETTERS

        forms = PERSIAN_LETTERS[char]

        if connects_prev and connects_next:
            reshaped.append(forms[2])  
        elif connects_prev:
            reshaped.append(forms[3])  
        elif connects_next:
            reshaped.append(forms[1])  
        else:
            reshaped.append(forms[0])  

    return "".join(reshaped)


def reshape_sentence(sentence: str) -> str:
    words = sentence.split(" ")
    reshaped_words = [reshape_word(word) for word in words]
    
    return " ".join(reversed(reshaped_words))


if __name__ == "__main__":
    s = "سلام دنیا"
    print(reshape_sentence(s))
