import datetime
import pathlib
import random
import string
import sys


class WordSearch:
    def __init__(self, cols, rows) -> None:
        self.cols = cols
        self.rows = rows
        self.cut_off = None
        self.wordSet = None
        self.board = None

    def add_word(self, word: str) -> None:
        self.wordSet.add(word)

    def buildSet(self, filename: str | None) -> None:
        self.cut_off = 0
        self.wordSet = set()
        fileObj = pathlib.Path(filename).open(encoding="utf-8")
        for line in fileObj:
            line_cleaned = line.strip().lower()
            self.add_word(line_cleaned)
            n_line = len(line_cleaned)
            self.cut_off = max(self.cut_off, n_line)
        fileObj.close()

    def generateBoard(self) -> None:
        print("\n\n")
        print("Board Size: %d X %d" % (self.rows, self.cols))
        alphabets = string.ascii_lowercase
        self.board = []
        for _i in range(self.rows):
            a_row = [random.choice(alphabets) for j in range(self.cols)]
            self.board.append(a_row)
            print(a_row)

    def isValid(self, word: str):
        return word in self.wordSet

    def getValidWords(self):
        result_set = set()
        for i in range(self.rows):
            for j in range(self.cols):
                kC = j
                nC = min(self.cols, kC + self.cut_off)
                while kC < nC:
                    q = kC
                    word = []
                    while q < nC:
                        word.append(self.board[i][q])
                        q += 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nC -= 1
                kC = j
                nC = max(-1, kC - self.cut_off)
                while kC > nC:
                    q = kC
                    word = []
                    while q > nC:
                        word.append(self.board[i][q])
                        q -= 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nC += 1
                kR = i
                nR = max(-1, kR - self.cut_off)
                while kR > nR:
                    p = kR
                    word = []
                    while p > nR:
                        word.append(self.board[p][j])
                        p -= 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nR += 1
                kR = i
                nR = min(self.rows, kR + self.cut_off)
                while kR < nR:
                    p = kR
                    word = []
                    while p < nR:
                        word.append(self.board[p][j])
                        p += 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nR -= 1
                kR = i
                kC = j
                nR = max(-1, kR - self.cut_off)
                nC = min(self.cols, kC + self.cut_off)
                while kR > nR and kC < nC:
                    p = kR
                    q = kC
                    word = []
                    while p > nR and q < nC:
                        word.append(self.board[p][q])
                        p -= 1
                        q += 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nC -= 1
                    nR += 1
                kR = i
                kC = j
                nR = max(-1, kR - self.cut_off)
                nC = max(-1, kC - self.cut_off)
                while kR > nR and kC > nC:
                    p = kR
                    q = kC
                    word = []
                    while p > nR and q > nC:
                        word.append(self.board[p][q])
                        p -= 1
                        q -= 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nC += 1
                    nR += 1
                kR = i
                kC = j
                nR = min(self.rows, kR + self.cut_off)
                nC = min(self.cols, kC + self.cut_off)
                while kR < nR and kC < nC:
                    p = kR
                    q = kC
                    word = []
                    while p < nR and q < nC:
                        word.append(self.board[p][q])
                        p += 1
                        q += 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nC -= 1
                    nR -= 1
                kR = i
                kC = j
                nR = min(self.rows, kR + self.cut_off)
                nC = max(-1, kC - self.cut_off)
                while kR < nR and kC > nC:
                    p = kR
                    q = kC
                    word = []
                    while p < nR and q > nC:
                        word.append(self.board[p][q])
                        p += 1
                        q -= 1
                    word = "".join(word)
                    if self.isValid(word):
                        result_set.add(word)
                    nC += 1
                    nR -= 1
        return result_set

    def display(self) -> None:
        result_set = self.getValidWords()
        print("\n\n")
        print("RESULT: total %d words found" % (len(result_set)))
        for word in result_set:
            print(word)


def printUsage() -> None:
    print("USAGE:")
    print("python   wordsearch.py   <word-list-file>   <cols>   <rows>")


def entryPoint() -> None:
    start = datetime.datetime.now()
    fileName = cols = rows = None
    try:
        if len(sys.argv) == 4:
            fileName = sys.argv[1]
            cols = int(sys.argv[2])
            rows = int(sys.argv[3])
        elif len(sys.argv) >= 2 and sys.argv[1] == "--help":
            printUsage()
    except Exception as e:
        print(e)
        printUsage()
    tws = WordSearch(cols, rows)
    tws.buildSet(fileName)
    tws.generateBoard()
    tws.display()
    end = datetime.datetime.now()
    print("\n")
    print("Execution Time (HH:MM:SS): %s" % (end - start))


if __name__ == "__main__":
    entryPoint()
