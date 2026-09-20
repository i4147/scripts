import string
from collections import deque
from multiprocessing import Pool
from pathlib import Path
from sys import exit
from time import perf_counter

from dh import is_binary_file
from fastwalk import walk_files

normal_chars = string.whitespace + string.ascii_letters + string.punctuation + string.digits
normal_chars += "۰۹۸۷۶۵۴۳۲۱چجحخهعفقثصپمنتالبیسشگکودرزط ءژًَُضقفغئِّآِظژررذذوکهغ₩﷼£€؟♧◇♡♤■□●○•°`☆▪¤《》¡¿"
normal_chars += "񰮊’“󱫷񖦩󤰙𾞶表ç󗟢ςα𜴭ﱶﵶ񄠼큶퍶홶쩶쭶챶콶쉶썶앶롶륶򺿇뱶덶땶򦢤뙶꡶ꩶꭶꉶꍶꕶ顶饶驶鱶齶鉶镶陶襶ô变艶葶虶究筶絶灶牶獶當癶桶楶汶󾱜扶摶晶奶并彶其坶䡶乶佶䕶䙶㡶㥶㩶㱶ぶㅶ㍶⥶ⱶ⵶⹶⽶ⅶ≶⑶᥶᩶ὶቶᙶ᝶ॶ୶౶ɶնٶݶ’英񲥉򸦑򂸬𬒱ࡱä𸯝𱧐…򇾴𓯊ر矩񁘿󨃢圆路򐿌캋䡰쾋买佰򮬫䱰䉰얋쒋䙰슋䑰䕰삋孰쎋”→幰彰屰솋印햋兰噰펋톋湰恰晰数ﾋ筰繰ﮋ穰絰癰๰཰౰袋ɰ蒋ٰݰ芋հᩰ肋鶋隋開钋ᅰᝰၰ邋⩰꾋꺋⥰ꪋꦋ≰⁰ⅰꎋ❰ꊋ뾋㩰붋㥰벋몋㽰㵰㱰󖕠랋ㅰ㙰뎋낋例事䶋쭰칰䦋쵰䚋䆋宋墋型咋压傋핰溋沋檋梋枋憋並殺箋ｰﵰ王皋炋議襰ઋಋ走ދڋ֋ҋ΋ʋࢋ腰荰ẋ顰魰鹰᪋鱰鉰遰ኋ⾋⺋ꡰⲋ⮋⪋⦋거ꭰ⚋▋⢋ꁰ⊋↋₋며뭰㾋㲋㦋㚋㖋㒋㎋띰뙰る򔤶򃚊끱ó򼉏–––———’™—🛡󧯚󱂑򰕧򲳳圆▫’숁봁밁렁딁뜁똁넁댁â눁각꼁ꨁ꜁ꄁ鼁頁鬁霁阁鄁踁褁蔁萁蘁老紁缁礁码焁氁椁栁欁昁愁态持戁封堁威圁倁刁䰁丁䤁䠁䬁䌁㰁㼁㘁、㌁ⴁ󔮮⼁⬁⨁✁℁∁ᰁḁ᠁ᘁခጁሁँࠁଁਁԁ܁؁ā́ȁხᇮᛮ៮᫮ᷮˮ׮ۮ߮𤱤૮೮㇮㛮㟮㣮㫮㿮⇮⋮⫮⯮ⳮ⻮⿮叮埮壮姮峮忮䃮䋮䏮䓮䣮䫮仮修狮瓮磮竮篮糮緮绮翮惮拮櫮泮淮濮郮釮问雮鯮胮蛮裮냮뇮뛮뫮믮볮뻮ꃮꓮ꣮꯮껮꿮ퟮ􈕚쇮쓮엮웮짮쳮﫮繴穴筴罴癴ﮏ絴畴牴硴灴ﲏ湴潴浴橴桴楴晴汴整慴年튏톏킏屴孴塴풏펏婴햏剴却側兴쎏슏䱴삏䩴䵴욏쒏좏쾏䍴䉴첏㹴캏㽴㩴㭴㡴㝴㑴몏뾏㍴붏뺏ꎏꊏ󆟚⹴⩴ꚏ⡴⥴ꮏ❴♴╴≴⍴⭴겏ⅴ銏ꦏ邏ᩴ随鎏ᥴᙴ换❌ᑴ龏๴芏ུ蚏𑳳烻ٴݴ讏մɴʹ趏袏炏瞏皏ﭴ璏箏福綏纏悏粏斏撏梏沏涏喏宏푴해퉴序퍴텴클墏챴䂏쩴䚏존䎏䮏이䆏亏䶏拻뽴면㖏롴㦏덴񀆔녴㲏⊏건굴₏꽴↏ꭴ⮏⪏⦏ꝴ⺏ⶏត魴顴ᚏ陴靴镴ẏᶏ鍴ʏ赴ޏڏ֏ҏ衴譴এ蕴ྏ葴ຏ腴ಏ࢏񊅟񃗵󇀄󳬗볻󒀒񘁢𩦻񰇌🦀񰃭󯣁􍳝—’􉃳򧯟䞉䆉䂉䎉䮉垉厉嶉墉安憉涉榉殉檉疉炉玉粉羉禉։҉މډʉඉಉᒉႉᶉᲉẉᮉ᪉➉⚉₉⊉ⲉ⺉⦉⢉⮉⪉ら㶉㾉㦉㢉㪉쒉삉쎉쾉좉행풉톉펉􉴗ﶉﲉﮉ憎蒉螉肉莉芉貉辉覉袉閉鞉銉馉颉骉ꚉꎉꊉ궉꾉꺉ꦉꢉꮉ떉뚉놉늉벉뺉몉"


def process_file(fp) -> bool:
    seen = set()
    if is_binary_file(fp):
        return False
    if not fp.exists():
        return False
    nl = ""
    with fp.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            cleaned = str(line).strip().lower()
            for i in range(len(cleaned)):
                if cleaned[i] not in normal_chars and cleaned[i] not in seen:
                    nl += cleaned[i]
                    seen.update(cleaned[i])
                    print(f"[{fp.name}] --> {cleaned[i]}")
    with Path("/sdcard/emoji").open("a", encoding="utf-8") as fo:
        fo.write(" ".join(list(nl)))
    return True


def main() -> None:
    start = perf_counter()
    files = []
    dir = "/data/data/com.termux"
    for pth in walk_files(dir):
        path = Path(pth)
        if path.is_symlink():
            continue
        if path.is_file():
            files.append(path)
    with Pool(8) as p:
        pending = deque()
        for f in files:
            pending.append(p.apply_async(process_file, ((f),)))
            if len(pending) > 16:
                pending.popleft().get()
        while pending:
            pending.popleft().get()
    print(f"{perf_counter() - start} seconds")


if __name__ == "__main__":
    exit(main())
