import urllib.request as ur
import androidhelper
import qpy
from qsl4ahelper.fullscreenwrapper2 import *

droid = androidhelper.Android()


class MainScreen(Layout):
    def __init__(self) -> None:
        super().__init__(
            '<?xml version="1.0" encoding="utf-8"?>\n<LinearLayout\n    android:layout_width="fill_parent"\n    android:layout_height="fill_parent"\n    android:background="#ff0E4200"\n    android:orientation="vertical"\n    xmlns:android="http://schemas.android.com/apk/res/android">\n    <ImageView\n        android:id="@+id/logo"\n        android:layout_width="fill_parent"\n        android:layout_height="0px"\n        android:layout_weight="10"\n    />\n    <LinearLayout\n        android:layout_width="fill_parent"\n        android:layout_height="0px"\n        android:orientation="horizontal"\n        android:layout_weight="20">\n        <TextView\n            android:layout_width="fill_parent"\n            android:layout_height="fill_parent"\n            android:textSize="8dp"\n            android:text="Hello, QPython"\n            android:textColor="#ffffffff"\n            android:layout_weight="1"\n            android:gravity="center"\n        />\n    </LinearLayout>\n    <ListView\n        android:id="@+id/data_list"\n        android:layout_width="fill_parent"\n        android:layout_height="0px"\n        android:layout_weight="55"/>\n    <LinearLayout\n        android:layout_width="fill_parent"\n        android:layout_height="0px"\n        android:orientation="horizontal"\n        android:layout_weight="8">\n        <Button\n            android:layout_width="fill_parent"\n            android:layout_height="fill_parent"\n            android:text="Load"\n            android:id="@+id/but_load"\n            android:textSize="8dp"\n            android:background="#ffEFC802"\n            android:textColor="#ffffffff"\n            android:layout_weight="1"\n            android:gravity="center"/>\n        <Button\n            android:layout_width="fill_parent"\n            android:layout_height="fill_parent"\n            android:text="Exit"\n            android:id="@+id/but_exit"\n            android:textSize="8dp"\n            android:background="#ff06AF00"\n            android:textColor="#ffffffff"\n            android:layout_weight="1"\n            android:gravity="center"/>\n    </LinearLayout>\n</LinearLayout>\n',
            "SL4AApp",
        )

    def on_show(self) -> None:
        self.views.but_exit.add_event(click_EventHandler(self.views.but_exit, self.exit))
        self.views.but_load.add_event(click_EventHandler(self.views.but_load, self.load))

    def on_close(self) -> None:
        pass

    def load(self, view, dummy) -> None:
        droid = FullScreenWrapper2App.get_android_instance()
        droid.makeToast("Load")
        saved_logo = qpy.tmp + "/qpy.logo"
        ur.urlretrieve("https://www.qpython.org/static/img_logo.png", saved_logo)
        self.views.logo.src = "file://" + saved_logo

    def exit(self, view, dummy) -> None:
        droid = FullScreenWrapper2App.get_android_instance()
        droid.makeToast("Exit")
        FullScreenWrapper2App.close_layout()


if __name__ == "__main__":
    FullScreenWrapper2App.initialize(droid)
    FullScreenWrapper2App.show_layout(MainScreen())
    FullScreenWrapper2App.eventloop()
