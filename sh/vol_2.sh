#! /bin/bash
DWM=$HOME/scripts
this=_vol
text_color="^c
muted_color="^c
empty_color="^c
signal=$(echo "^s$this^" | sed 's/_//')
update() {
    bar_icon=''
    vol_text=$(amixer sget Master | grep 'Right:' | awk -F'[][]' '{ print $2 }' | cut -d % -f 1)
    muted=$(amixer sget Master | grep off)
    if [ "$vol_text" -eq 0 ];  then vol_text="00"; vol_icon=" 婢";
    elif [ "$vol_text" -lt 10 ]; then vol_icon=" 奔"; vol_text=0$vol_text;
    elif [ "$vol_text" -le 50 ]; then vol_icon=" 奔";
    else vol_icon=" 墳"; fi
    if [[ "$muted" ]]; then
        vol_icon=" 婢"
        text=' '
        sed -i '/^export '$this'=.*$/d' $DWM/statusbar/temp
        printf "export %s='%s%s%s%s'\n" $this "$signal" "$muted_color" "$vol_icon" "$text" >> $DWM/statusbar/temp
    else
        vol=$((vol_text))
        vol=$((vol/10-1))
        text="${bar_icon}$(printf "%${vol}s")"
        text=${text// /$bar_icon}
        echo "$vol_text%"
        em_len=$((8-vol))
        em="${bar_icon}$(printf "%${em_len}s")"
        em=${em// /$bar_icon}
        sed -i '/^export '$this'=.*$/d' $DWM/statusbar/temp
        printf "export %s='%s%s%s%s%s'\n" $this "$signal" "$text_color" "$vol_icon $text" "$empty_color" "$em " >> $DWM/statusbar/temp
    fi
}
notify() {
    notify-send -r 9527 Volume "$(update)" -i audio-volume-medium
}
call_vol() {
    mx=`xdotool getmouselocation --shell | grep X= | sed 's/X=//'`
    my=`xdotool getmouselocation --shell | grep Y= | sed 's/Y=//'`
    st -t statusutil_vol -g 45x20+$((mx - 328))+$((my + 20)) -c FNG -e alsamixer
}
click() {
    case "$1" in
        M) notify                                           ;;
        L) amixer set Master toggle -q; notify ;;
        R) call_vol            ;;
        U) amixer set Master 5%+ -q; notify ;;
        D) amixer set Master 5%- -q; notify ;;
    esac
}
case "$1" in
    click) click $2 ;;
    notify) notify ;;
    *) update ;;
esac
