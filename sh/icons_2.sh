#! /bin/bash
DWM=$HOME/scripts
this=_icons
color="^c
signal=$(echo "^s$this^" | sed 's/_//')
update() {
    icons=("")
    icons=(${icons[@]} "")
    icons=(${icons[@]} "")
    sed -i '/^export '$this'=.*$/d' $DWM/statusbar/temp
    text=" ${icons[@]} "
    printf "export %s='%s%s%s%s'\n" $this "$signal" "$color" "$text" >> $DWM/statusbar/temp
}
notify() {
    texts=""
    [ "$(/usr/bin/bluetooth | grep 'bluetooth = on')" ] && texts="$texts\n airpods pro 2 已链接"
    [ "$texts" != "" ] && notify-send " Info" "$texts" -r 9527
}
call_menu() {
    case $(echo -e '关机\n重启\n休眠\n挂起\n锁定' | rofi -dmenu -window-title power) in
        关机) poweroff ;;
        重启) reboot ;;
        休眠) sudo systemctl hibernate ;;
        挂起) sudo systemctl suspend ;;
        锁定) sh $HOME/scripts/lockscreen.sh ;;
    esac
}
click() {
    case "$1" in
        L) notify; feh --randomize --bg-fill /data/data/wallpaper/*.png ;;
        M) call_menu ;;
        R) feh --randomize --bg-fill /data/data/wallpaper/1.png
    esac
}
case "$1" in
    click) click $2 ;;
    notify) notify ;;
    *) update ;;
esac
