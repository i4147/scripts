#! /bin/bash
DWM=$HOME/scripts
this=_wifi
icon_color="^c
text_color="^c
signal=$(echo "^s$this^" | sed 's/_//')
[ ! "$(command -v nmcli)" ] && echo command not found: nmcli && exit
wifi_grep_keyword="已连接 到"
wifi_disconnected="未连接"
update() {
	wifi_icon="直"
	wifi_text=$(nmcli | grep "$wifi_grep_keyword" | awk -F "$wifi_grep_keyword" '{print $2}')
	[ "$wifi_text" = "" ] && wifi_text=$wifi_disconnected
	icon=" $wifi_icon "
	text="$wifi_text "
	sed -i '/^export '$this'=.*$/d' $DWM/statusbar/temp
	printf "export %s='%s%s%s%s%s'\n" $this "$signal" "$icon_color" "$icon" "$text_color" "$text" >>$DWM/statusbar/temp
}
notify() {
	update
	notify-send -r 9527 "$wifi_icon Wifi" "\n$wifi_text"
}
call_nm() {
	pid1=$(ps aux | grep 'st -t statusutil' | grep -v grep | awk '{print $2}')
	pid2=$(ps aux | grep 'st -t statusutil_nm' | grep -v grep | awk '{print $2}')
	mx=$(xdotool getmouselocation --shell | grep X= | sed 's/X=//')
	my=$(xdotool getmouselocation --shell | grep Y= | sed 's/Y=//')
	kill $pid1 && kill $pid2 || st -t statusutil_nm -g 60x25+$((mx - 240))+$((my + 20)) -c FGN -e 'nmtui-connect'
}
click() {
	case "$1" in
	L) notify ;;
	R) call_nm ;;
	esac
}
case "$1" in
click) click $2 ;;
notify) notify ;;
*) update ;;
esac
