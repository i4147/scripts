#! /bin/bash
BLANK='
CLEAR='
DEFAULT='
TEXT='
WRONG='
VERIFYING='
i3lock \
--insidever-color=$CLEAR     \
--ringver-color=$VERIFYING   \
\
--insidewrong-color=$CLEAR   \
--ringwrong-color=$WRONG     \
\
--inside-color=$BLANK        \
--ring-color=$DEFAULT        \
--line-color=$BLANK          \
--separator-color=$DEFAULT   \
\
--verif-color=$TEXT          \
--wrong-color=
--time-color=$TEXT           \
--date-color=
--layout-color=$TEXT         \
--keyhl-color=$WRONG         \
--bshl-color=$WRONG          \
\
--screen 1                   \
--blur 3                     \
--clock                      \
--force-clock                      \
--indicator                  \
--time-str="%H:%M:%S"        \
--time-size=128              \
--date-str="%A  %Y-%m-%d"       \
--date-size=30              \
--wrong-size=60              \
--verif-size=60              \
--radius=300             \
--pointer default     \
--show-failed-attempts
xdotool mousemove_relative 1 1
