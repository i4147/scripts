#! /bin/bash
DWM=$HOME/scripts
this=_tomato
icon_color="^c
text_color="^c
signal=$(echo "^s$this^" | sed 's/_//')
update() {
	icon="tomato"
	light_text=''
	sed -i '/^export '$this'=.*$/d' $DWM/statusbar/temp
	printf "export %s=\"%s%s%s%s%s\"\n" $this "$signal" "$icon_color" "$icon" "$text_color" "$light_text" >>$DWM/statusbar/temp
}
click() {
	case "$1" in
	L) tty-clock -s -c -C 5 -D -r ;;
	esac
}
case "$1" in
click) click $2 ;;
notify) notify ;;
*) update ;;
esac
