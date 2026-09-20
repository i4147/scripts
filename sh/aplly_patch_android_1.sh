#!/system/bin/sh
if applypatch -c /system/recovery-from-boot.p 9d65482666c5bc62fcf19e9ddd1903eaf6f7aff2 && ! applypatch -c EMMC:/dev/block/platform/13540000.dwmmc0/by-name/RECOVERY:22581536:4861891d74f59be8c69724763acfed4d86db009c; then
  applypatch EMMC:/dev/block/platform/13540000.dwmmc0/by-name/BOOT:19583264:f5479f72646ca53fd237330af54c530eb899f868 EMMC:/dev/block/platform/13540000.dwmmc0/by-name/RECOVERY 4861891d74f59be8c69724763acfed4d86db009c 22581536 f5479f72646ca53fd237330af54c530eb899f868:/system/recovery-from-boot.p || echo 454 > /cache/fota/fota.status
else
  log -t install_recovery "Recovery image already installed or recovery patch file doesn't have any of expected sha1 sums"
if [ -e /cache/recovery/command ] ; then
  PACKAGE_PATH=""
  SEARCH_COMMAND="--update_package"
  PATH_POS=16
  if [ -e '/system/bin/grep' ] ; then
    PACKAGE_PATH=`cat /cache/recovery/command | grep 'update_package'`
    PACKAGE_ORG_PATH=`cat /cache/recovery/command | grep 'update_org_package'`
    if [ "$PACKAGE_ORG_PATH" != "" ] ; then
      PACKAGE_PATH=$PACKAGE_ORG_PATH
      SEARCH_COMMAND="--update_org_package"
      PATH_POS=20
    fi
    if [ -e /cache/recovery/saved" ] ; then
      rm -rf /cache/recovery/saved
    fi
    if [ -e /data/.recovery/saved" ] ; then
      rm -rf /data/.recovery/saved
    fi
  fi
  if [ "$PACKAGE_PATH" != "" ] ; then
    for PACKAGE_LINE in $PACKAGE_PATH
    do
      if [ ${PACKAGE_LINE:0:$PATH_POS} == $SEARCH_COMMAND ] ; then
        break
      fi
    done
    let PATH_POS+=1
    PACKAGE_PATH=${PACKAGE_LINE:$PATH_POS}
    if [ "$PACKAGE_PATH" != "" ] ; then
      rm $PACKAGE_PATH
      log -t install_recovery "install_recovery tried to remove the delta"
    fi
  fi
  if [ ${PACKAGE_PATH:0:5} == "/data" ] ; then
    echo $PACKAGE_PATH > /cache/fota/fota_path_command
    chown system:system /cache/fota/fota_path_command
  fi
  rm /cache/recovery/command


