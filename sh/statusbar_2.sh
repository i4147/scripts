#!/usr/bin/sh
DWM=$HOME/scripts
touch $DWM/statusbar/temp
tempfile=$thisdir/temp
update() {
    [ ! "$1" ] && refresh && return
    bash $DWM/statusbar/packages/$1.sh
    shift 1; update $*
}
click() {
    [ ! "$1" ] && return
    bash $DWM/statusbar/packages/$1.sh click $2
    update $1
    refresh
}
refresh() {
    echo "refresh"
    _icons=''; _wifi=''; _cpu=''; _mem=''; _date=''; _vol=''; _bat=''; _music=''; _light=''; _tomato=''
    source $DWM/statusbar/temp
    xsetroot -name "$_icons$_light$_tomato$_music$_wifi$_cpu$_mem$_date$_vol$_bat"
}
cron() {
    echo > $DWM/statusbar/temp
    let i=0
    while true; do
        to=()
        [ $((i % 10)) -eq 0 ]  && to=(${to[@]} wifi)
        [ $((i % 20)) -eq 0 ]  && to=(${to[@]} cpu mem vol icons)
        [ $((i % 300)) -eq 0 ] && to=(${to[@]} bat light tomato)
        [ $((i % 5)) -eq 0 ]   && to=(${to[@]} date music)
        update ${to[@]}
        sleep 5; let i+=5
    done &
}
case $1 in
    cron) cron ;;
    update) shift 1; update $* ;;
    updateall|check) update icons music wifi cpu mem date vol light bat tomato;;
    *) click $1 $2 ;;
esac
