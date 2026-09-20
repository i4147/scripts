# Create config directory if it doesn't exist
#mkdir -p $PREFIX/etc/tor

# Create a basic torrc file
#cat > $PREFIX/etc/tor/torrc << EOF
#SOCKSPort 9050
#ControlPort 9051
#DataDirectory $PREFIX/var/lib/tor
#Log notice file $PREFIX/var/log/tor/notices.log
#EOF

#mkdir -p $PREFIX/var/lib/tor
#mkdir -p $PREFIX/var/log/tor

# Start Tor in the background
#tor &

# Or with custom config file
#tor -f $PREFIX/etc/tor/torrc &

# Check if Tor process is running
#ps aux | grep tor

# Check the logs
#cat $PREFIX/var/log/tor/notices.log

#curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org

#wget -e use_proxy=yes -e http_proxy=socks5h://127.0.0.1:9050 https://check.torproject.org
#pkg install proxychains-ng -y

# Configure proxychains
echo "socks5 127.0.0.1 9050" >>$PREFIX/etc/proxychains.conf

# Use with any command
#proxychains4 curl https://check.torproject.org

# Start Tor if not running
#if ! pgrep -x "tor" > /dev/null; then
#    tor > /dev/null 2>&1 &
#    echo "Tor started..."
#fi

# Set proxy environment variables
#export HTTP_PROXY="socks5h://127.0.0.1:9050"
#export HTTPS_PROXY="socks5h://127.0.0.1:9050"
#export ALL_PROXY="socks5h://127.0.0.1:9050"

# Optional: alias nvim with proxychains
# alias nvim='proxychains -q nvim'
#git config --global http.proxy socks5h://127.0.0.1:9050
#git config --global https.proxy socks5h://127.0.0.1:9050
wget -e use_proxy=yes -e http_proxy=socks5h://127.0.0.1:9050 https://check.torproject.org
