    main_menu_items=('1. set wallpaper' '2. update statusbar' '3. toggle server' '4. set backlight' '5. power menu' '6. lock screen')
    main_menu_cmds=(
        'feh --randomize --bg-fill /data/data/wallpaper/*.png; show_main_menu'
        'coproc ($DWM/statusbar/statusbar.sh updateall > /dev/null 2>&1); show_main_menu'
        'show_toggle_server_menu'
        'show_set_backlight_menu'
        'show_power_menu'
        'sh ~/scripts/lockscreen.sh*'
    )
    toggle_server_menu_items[2]='open picom'
    toggle_server_menu_cmds[2]='coproc (picom --config ~/.config/picom/picom.conf > /dev/null 2>&1)'
    [ "$(ps aux | grep picom | grep -v 'grep\|rofi\|nvim')" ] && toggle_server_menu_items[2]='close picom'
    [ "$(ps aux | grep picom | grep -v 'grep\|rofi\|nvim')" ] && toggle_server_menu_cmds[2]='killall picom'
    set_backlight_menu_items=('内置屏幕' '外置屏幕')
    set_backlight_menu_cmds=('show_set_backlight_menu2 内置屏幕' 'show_set_backlight_menu2 外置屏幕')
    set_backlight_menu_items2=('1.0' '0.8' '0.6' '0.4' '0.2')
    power_menu_items=('poweroff' 'reboot')
    power_menu_cmds=('sudo poweroff' 'sudo reboot')
    show_main_menu() {
        echo -en "\0new-selection\x1ftrue\n"
        echo -e "\0prompt\x1fmenu\n"
        echo -en "\0data\x1fMAIN_MENU\n"
        for item in "${main_menu_items[@]}"; do
            echo "$item"
        done
    }
    show_toggle_server_menu() {
        echo -en "\0new-selection\x1ftrue\n"
        echo -e "\0prompt\x1ftoggle\n"
        echo -en "\0data\x1fTOGGLE_SERVER_MENU\n"
        for item in "${toggle_server_menu_items[@]}"; do
            echo "$item"
        done
    }
    show_set_backlight_menu() {
        echo -en "\0new-selection\x1ftrue\n"
        echo -e "\0prompt\x1fselect\n"
        echo -en "\0data\x1fSET_BACKLIGHT_MENU\n"
        for item in "${set_backlight_menu_items[@]}"; do
            echo "$item"
        done
    }
    show_set_backlight_menu2() {
        echo -en "\0new-selection\x1ftrue\n"
        echo -e "\0prompt\x1flight\n"
        echo -en "\0data\x1fSET_BACKLIGHT_$1\n"
        for item in "${set_backlight_menu_items2[@]}"; do
            echo "$item"
        done
    }
    show_power_menu() {
        echo -en "\0new-selection\x1ftrue\n"
        echo -e "\0prompt\x1fpower\n"
        echo -en "\0data\x1fPOWER_MENU\n"
        for item in "${power_menu_items[@]}"; do
            echo "$item"
        done
    }
    judge() {
        [ "$ROFI_DATA" ] && MENU=$ROFI_DATA || MENU="MAIN_MENU"
        case $MENU in
            MAIN_MENU)
                for i in "${!main_menu_items[@]}"; do
                    [ "$*" = "${main_menu_items[$i]}" ] && eval "${main_menu_cmds[$i]}"
                done
            ;;
            TOGGLE_SERVER_MENU)
                for i in "${!toggle_server_menu_items[@]}"; do
                    [ "$*" = "${toggle_server_menu_items[$i]}" ] && eval "${toggle_server_menu_cmds[$i]}"
                done
            ;;
            SET_BACKLIGHT_MENU)
                for i in "${!set_backlight_menu_items[@]}"; do
                    [ "$*" = "${set_backlight_menu_items[$i]}" ] && eval "${set_backlight_menu_cmds[$i]}"
                done
            ;;
            SET_BACKLIGHT_内置屏幕)
                out=eDP-1; light=$1
                xrandr --output $out --brightness $light
            ;;
            SET_BACKLIGHT_外置屏幕)
                out=$(xrandr | grep -v eDP-1 | grep -w 'connected' | awk '{print $1}'); light=$1
                xrandr --output $out --brightness $light
            ;;
            POWER_MENU)
                for i in "${!power_menu_items[@]}"; do
                    [ "$*" = "${power_menu_items[$i]}" ] && eval "${power_menu_cmds[$i]}"
                done
        esac
    }
    [ ! "$*" ] && show_main_menu || judge $*
